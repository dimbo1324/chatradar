"""`SearchIndex` over the SQLite FTS5 table `threads_fts(thread_id, chat_id, body)`.

Free user text never reaches FTS5 as syntax: it is cut into word tokens, each one quoted.
There is no Russian or Spanish stemmer, so words longer than four letters become prefix
queries: Russian "kvartiru" and "kvartira" (transliterated) both match "kvarti"*.
"""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING, Any

from sqlalchemy import bindparam, column, delete, func, literal_column, select, table

from chatradar.domain.models import ThreadHit
from chatradar.storage.db.rows import chunks, to_thread
from chatradar.storage.db.tables import messages, threads

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy import ColumnClause, ColumnElement
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

    from chatradar.domain.models import SearchFilters

MAX_TOKENS = 16
SNIPPET_TOKENS = 16
MARK_OPEN, MARK_CLOSE = "[[", "]]"

_WORD = re.compile(r"[^\W_]+")
# unicode61 strips diacritics only from Latin letters, so the Cyrillic yo is folded to ie
# by hand on both sides; snippets therefore show ie where the message had yo.
_YO = str.maketrans("\u0451\u0401", "\u0435\u0415")

threads_fts = table("threads_fts", column("thread_id"), column("chat_id"), column("body"))
_FTS: ColumnClause[Any] = literal_column("threads_fts")


def query_terms(text: str) -> list[str]:
    """Quoted FTS5 terms for free text; words longer than 4 letters become prefixes."""
    terms: list[str] = []
    folded = unicodedata.normalize("NFKC", text).casefold().translate(_YO)
    for token in _WORD.findall(folded):
        term = f'"{token[: max(4, len(token) - 2)]}"*' if len(token) > 4 else f'"{token}"'
        if term not in terms:
            terms.append(term)
    return terms[:MAX_TOKENS]


def _body(texts: Sequence[str]) -> str:
    """Joined thread text; marker look-alikes are broken up so snippets stay unambiguous."""
    joined = "\n".join(t for t in texts if t).translate(_YO)
    return joined.replace(MARK_OPEN, "[ [").replace(MARK_CLOSE, "] ]")


class Fts5SearchIndex:
    def __init__(self, engine: AsyncEngine) -> None:
        if engine.dialect.name != "sqlite":
            raise ValueError("Fts5SearchIndex needs SQLite; use the Postgres index there")
        self._engine = engine

    async def index_threads(self, thread_ids: Sequence[str]) -> None:
        ids = list(dict.fromkeys(thread_ids))
        async with self._engine.begin() as conn:
            for part in chunks(ids):
                await _reindex(conn, part)

    async def rebuild(self) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(delete(threads_fts))
            ids = list((await conn.execute(select(threads.c.thread_id))).scalars())
            for part in chunks(ids):
                await _reindex(conn, part)

    async def search(self, query: str, filters: SearchFilters) -> list[ThreadHit]:
        terms = query_terms(query)
        if not terms:
            return []
        async with self._engine.connect() as conn:
            hits = await self._match(conn, " ".join(terms), filters)
            if not hits and len(terms) > 1:
                hits = await self._match(conn, " OR ".join(terms), filters)
        return hits

    async def _match(
        self, conn: AsyncConnection, match: str, filters: SearchFilters
    ) -> list[ThreadHit]:
        rank = func.bm25(_FTS).label("bm25_rank")
        snippet = func.snippet(_FTS, 2, MARK_OPEN, MARK_CLOSE, "...", SNIPPET_TOKENS).label(
            "snippet"
        )
        root = messages.alias("root")
        where: list[ColumnElement[bool]] = [_FTS.op("MATCH")(bindparam("match", match))]
        if filters.source is not None:
            where.append(threads.c.source == filters.source.value)
        if filters.chat_id is not None:
            where.append(threads.c.chat_id == filters.chat_id)
        if filters.date_from is not None:
            where.append(threads.c.ended_at >= filters.date_from)
        if filters.date_to is not None:
            where.append(threads.c.started_at <= filters.date_to)
        stmt = (
            select(threads, rank, snippet, root.c.link.label("root_link"))
            .select_from(
                threads_fts.join(threads, threads.c.thread_id == threads_fts.c.thread_id).outerjoin(
                    root,
                    (root.c.source == threads.c.source)
                    & (root.c.chat_id == threads.c.chat_id)
                    & (root.c.msg_id == threads.c.root_msg_id),
                )
            )
            .where(*where)
            .order_by(rank, threads.c.started_at.desc())
            .limit(filters.limit)
        )
        rows = (await conn.execute(stmt)).mappings().all()
        return [
            ThreadHit(
                thread=to_thread(row),
                score=-float(row["bm25_rank"]),
                snippet=str(row["snippet"]),
                link=row["root_link"],
            )
            for row in rows
        ]


async def _reindex(conn: AsyncConnection, thread_ids: Sequence[str]) -> None:
    await conn.execute(delete(threads_fts).where(threads_fts.c.thread_id.in_(thread_ids)))
    stmt = (
        select(threads.c.thread_id, threads.c.chat_id, messages.c.text)
        .join(messages, messages.c.thread_id == threads.c.thread_id)
        .where(threads.c.thread_id.in_(thread_ids), messages.c.is_noise.is_not(True))
        .order_by(threads.c.thread_id, messages.c.date, messages.c.msg_id)
    )
    texts: dict[str, list[str]] = {}
    chat_of: dict[str, str] = {}
    for thread_id, chat_id, text in await conn.execute(stmt):
        texts.setdefault(thread_id, []).append(text)
        chat_of[thread_id] = chat_id
    rows: list[dict[str, Any]] = [
        {"thread_id": thread_id, "chat_id": chat_of[thread_id], "body": body}
        for thread_id, parts in texts.items()
        if (body := _body(parts))
    ]
    if rows:
        await conn.execute(threads_fts.insert(), rows)
