"""The read-only side of the search index: queries over `_search.db`.

Every query value travels as a bound parameter. The typed text becomes one quoted FTS5 phrase
(quotes doubled), so `AND`, `OR`, `NEAR`, `*`, `%` and `_` are plain characters. A reader has
a connection of its own and a lock, so a window may call it from whichever worker thread it
likes, one call at a time.
"""

from __future__ import annotations

import contextlib
import sqlite3
import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from chatimport.records import parse_dt
from chatimport.search_db import SearchError, connect_reader, database_path
from chatimport.search_fold import search_key
from chatimport.search_types import (
    MIN_INDEXED_LENGTH,
    ChatChoice,
    ContextMessage,
    IndexState,
    IndexStatus,
    SearchHit,
    SearchPage,
    SearchQuery,
)
from chatimport.telegram.mapper import message_link
from chatimport.textnorm import fold

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from chatimport.search_types import SearchBackend

MAX_LIMIT: Final = 1000
SHORT_SCAN_CAP: Final = 20000
MAX_CONTEXT: Final = 100

_HIT_COLUMNS: Final = "m.chat_id, m.msg_id, m.date, m.text, m.edited, c.title, c.username, c.folder"
_NEWEST_FIRST: Final = "ORDER BY m.date DESC, m.msg_id DESC, m.chat_id DESC"


def _moment(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, UTC)


def _stamp(value: datetime) -> int:
    return int((value if value.tzinfo is not None else value.replace(tzinfo=UTC)).timestamp())


def fts_phrase(key: str) -> str:
    return '"' + key.replace('"', '""') + '"'


def _filters(query: SearchQuery) -> tuple[list[str], list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if query.chat_ids is not None:
        ids = sorted(query.chat_ids)
        clauses.append(f"m.chat_id IN ({', '.join('?' * len(ids))})")
        params.extend(ids)
    if query.since is not None:
        clauses.append("m.date >= ?")
        params.append(_stamp(query.since))
    if query.until is not None:
        clauses.append("m.date < ?")
        params.append(_stamp(query.until))
    return clauses, params


class SearchReader:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.Lock()

    @contextlib.contextmanager
    def _guard(self) -> Generator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
            except sqlite3.Error as error:
                raise SearchError("the search index cannot be read right now") from error

    def close(self) -> None:
        with self._lock, contextlib.suppress(sqlite3.Error):
            self._conn.close()

    def search(self, query: SearchQuery) -> SearchPage:
        key = search_key(query.text)
        if not key or (query.chat_ids is not None and not query.chat_ids):
            return SearchPage((), 0, query)
        clauses, params = _filters(query)
        limit = min(max(query.limit, 0), MAX_LIMIT)
        offset = max(query.offset, 0)
        with self._guard() as conn:
            if len(key) >= MIN_INDEXED_LENGTH:
                where = " AND ".join(["fts MATCH ?", *clauses])
                source = "fts JOIN messages m ON m.id = fts.rowid"
                args = [fts_phrase(key), *params]
                total_sql = f"SELECT COUNT(*) FROM {source} WHERE {where}"  # noqa: S608
                total_args = args
            else:
                inner = (
                    f"(SELECT * FROM messages m WHERE {' AND '.join(clauses or ['1'])} "  # noqa: S608
                    f"{_NEWEST_FIRST} LIMIT ?)"
                )
                source = inner + " m"
                where = "instr(m.folded, ?) > 0"
                args = [*params, SHORT_SCAN_CAP, key]
                total_sql = f"SELECT COUNT(*) FROM {source} WHERE {where}"  # noqa: S608
                total_args = args
            total = int(conn.execute(total_sql, total_args).fetchone()[0])
            rows = (
                conn.execute(
                    f"SELECT {_HIT_COLUMNS} FROM {source} "  # noqa: S608
                    f"JOIN chats c ON c.chat_id = m.chat_id WHERE {where} "
                    f"{_NEWEST_FIRST} LIMIT ? OFFSET ?",
                    [*args, limit, offset],
                ).fetchall()
                if limit
                else []
            )
        hits = tuple(
            SearchHit(
                chat_id=row[0],
                chat_title=row[5] or row[7],
                msg_id=row[1],
                date=_moment(row[2]),
                text=row[3],
                edited=bool(row[4]),
                link=message_link(row[0], row[6], row[1]),
            )
            for row in rows
        )
        return SearchPage(hits, total, query)

    def context(
        self, chat_id: int, msg_id: int, before: int = 3, after: int = 3
    ) -> tuple[ContextMessage, ...]:
        before = min(max(before, 0), MAX_CONTEXT)
        after = min(max(after, 0), MAX_CONTEXT)
        columns = "msg_id, date, text, edited"
        with self._guard() as conn:
            target = conn.execute(
                f"SELECT {columns} FROM messages WHERE chat_id = ? AND msg_id = ?",  # noqa: S608
                (chat_id, msg_id),
            ).fetchone()
            if target is None:
                return ()
            older = conn.execute(
                f"SELECT {columns} FROM messages WHERE chat_id = ? AND msg_id < ? "  # noqa: S608
                "ORDER BY msg_id DESC LIMIT ?",
                (chat_id, msg_id, before),
            ).fetchall()
            newer = conn.execute(
                f"SELECT {columns} FROM messages WHERE chat_id = ? AND msg_id > ? "  # noqa: S608
                "ORDER BY msg_id ASC LIMIT ?",
                (chat_id, msg_id, after),
            ).fetchall()
        rows = [*reversed(older), target, *newer]
        return tuple(
            ContextMessage(
                msg_id=row[0],
                date=_moment(row[1]),
                text=row[2],
                edited=bool(row[3]),
                is_target=row[0] == msg_id,
            )
            for row in rows
        )

    def chats(self) -> tuple[ChatChoice, ...]:
        with self._guard() as conn:
            rows = conn.execute(
                "SELECT chat_id, title, folder, messages FROM chats WHERE messages > 0"
            ).fetchall()
        choices = [ChatChoice(row[0], row[1] or row[2], row[3]) for row in rows]
        return tuple(sorted(choices, key=lambda c: (fold(c.title), c.chat_id)))

    def status(self) -> IndexStatus:
        with self._guard() as conn:
            meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
            indexed = int(
                conn.execute("SELECT COALESCE(SUM(messages), 0) FROM chats").fetchone()[0]
            )
        try:
            state = IndexState(meta.get("state", IndexState.BUILDING.value))
        except ValueError:
            state = IndexState.BUILDING
        try:
            total = int(meta.get("total", "0"))
        except ValueError:
            total = 0
        stamp = meta.get("updated_at")
        try:
            updated = parse_dt(stamp) if stamp else None
        except ValueError:
            updated = None
        total = indexed if state is IndexState.READY else max(total, indexed)
        return IndexStatus(state, indexed, total, updated)


def open_reader(root: Path) -> SearchBackend | None:
    """A read-only view of `<root>/_search.db`, or None when there is no usable index."""
    conn = connect_reader(database_path(root))
    return SearchReader(conn) if conn is not None else None
