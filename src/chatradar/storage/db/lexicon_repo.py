"""SQL implementation of `LexiconRepository` and `LabelRepository`.

Dialect-specific statements stay here: insert-or-ignore for seeding and upsert for labels.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, insert, or_, select, update
from sqlalchemy.dialects import postgresql, sqlite

from chatradar.domain.evaluation import MessageLabel
from chatradar.domain.lexicon import (
    STAGE_LEXICON_KINDS,
    LexiconKind,
    LexiconSnapshot,
    LexiconSummary,
    LexiconTerm,
    TermExample,
    TermPage,
    TermSource,
    TermStatus,
    changes_active_set,
    next_status,
)
from chatradar.storage.db.rows import chunks, upsert
from chatradar.storage.db.tables import lexicon_state, lexicon_terms, message_labels

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy import RowMapping
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

    from chatradar.domain.lexicon import TermDecision, TermKey
    from chatradar.domain.ports import TermOrder

REVISION = "revision"
_APPLIED_PREFIX = "applied:"
_KEY_CHUNK = 300
"""Keys per query: three bound parameters each, well below SQLite's limit."""

_STATS_COLUMNS = ("occurrences", "chats", "authors", "score", "examples", "last_seen")

_ORDERS = {
    "score": (lexicon_terms.c.score.desc(),),
    "occurrences": (lexicon_terms.c.occurrences.desc(),),
    "recent": (lexicon_terms.c.last_seen.desc().nulls_last(),),
}
_TIEBREAK = (lexicon_terms.c.kind, lexicon_terms.c.lang, lexicon_terms.c.term)


def _utc(value: datetime | None) -> datetime | None:
    return None if value is None else value.astimezone(UTC)


def _term_values(term: LexiconTerm) -> dict[str, Any]:
    return {
        "kind": term.kind.value,
        "lang": term.lang,
        "term": term.term,
        "status": term.status.value,
        "source": term.source.value,
        "weight": term.weight,
        "occurrences": term.occurrences,
        "chats": term.chats,
        "authors": term.authors,
        "score": term.score,
        "examples": [
            {"source": e.source.value, "chat_id": e.chat_id, "msg_id": e.msg_id}
            for e in term.examples
        ],
        "first_seen": _utc(term.first_seen),
        "last_seen": _utc(term.last_seen),
        "decided_at": _utc(term.decided_at),
        "decided_by": term.decided_by,
        "note": term.note,
        "revision": term.revision,
    }


def _to_term(row: RowMapping) -> LexiconTerm:
    return LexiconTerm(
        kind=LexiconKind(row["kind"]),
        lang=row["lang"],
        term=row["term"],
        status=TermStatus(row["status"]),
        source=TermSource(row["source"]),
        weight=row["weight"],
        occurrences=row["occurrences"],
        chats=row["chats"],
        authors=row["authors"],
        score=row["score"],
        examples=tuple(TermExample.model_validate(e) for e in row["examples"] or ()),
        first_seen=row["first_seen"],
        last_seen=row["last_seen"],
        decided_at=row["decided_at"],
        decided_by=row["decided_by"],
        note=row["note"],
        revision=row["revision"],
    )


def _key_where(key: TermKey) -> Any:
    kind, lang, term = key
    c = lexicon_terms.c
    return (c.kind == kind.value) & (c.lang == lang) & (c.term == term)


def _key_filter(keys: Sequence[TermKey]) -> Any:
    return or_(*(_key_where(key) for key in keys))


class SqlLexiconRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._dialect = engine.dialect.name

    # ---------------------------------------------------------------- revision

    async def revision(self) -> int:
        async with self._engine.connect() as conn:
            return await self._state(conn, REVISION)

    async def applied_revision(self, stage: str) -> int:
        async with self._engine.connect() as conn:
            return await self._state(conn, _APPLIED_PREFIX + stage)

    async def set_applied_revision(self, stage: str, revision: int) -> None:
        stmt = upsert(self._dialect, lexicon_state, ("value",))
        async with self._engine.begin() as conn:
            await conn.execute(stmt, {"name": _APPLIED_PREFIX + stage, "value": revision})

    @staticmethod
    async def _state(conn: AsyncConnection, name: str) -> int:
        stmt = select(lexicon_state.c.value).where(lexicon_state.c.name == name)
        value = (await conn.execute(stmt)).scalar_one_or_none()
        return 0 if value is None else int(value)

    @staticmethod
    async def _bump(conn: AsyncConnection) -> int:
        """Move the revision by one in the caller's transaction and return the new value."""
        stmt = (
            update(lexicon_state)
            .where(lexicon_state.c.name == REVISION)
            .values(value=lexicon_state.c.value + 1)
        )
        if (await conn.execute(stmt)).rowcount == 0:
            await conn.execute(insert(lexicon_state).values(name=REVISION, value=1))
            return 1
        return await SqlLexiconRepository._state(conn, REVISION)

    # -------------------------------------------------------------------- read

    async def snapshot(self) -> LexiconSnapshot:
        c = lexicon_terms.c
        stmt = (
            select(c.kind, c.term)
            .where(c.status == TermStatus.ACTIVE.value)
            .order_by(c.kind, c.term, c.lang)
        )
        async with self._engine.connect() as conn:
            revision = await self._state(conn, REVISION)
            rows = (await conn.execute(stmt)).all()
        entries: dict[str, list[str]] = {}
        for kind, term in rows:
            terms = entries.setdefault(kind, [])
            if not terms or terms[-1] != term:
                terms.append(term)
        return LexiconSnapshot(
            revision=revision, entries={kind: tuple(terms) for kind, terms in entries.items()}
        )

    async def get_term(self, kind: LexiconKind, lang: str, term: str) -> LexiconTerm | None:
        stmt = select(lexicon_terms).where(_key_where((kind, lang, term)))
        async with self._engine.connect() as conn:
            row = (await conn.execute(stmt)).mappings().first()
        return _to_term(row) if row is not None else None

    async def list_terms(
        self,
        *,
        kind: LexiconKind | None = None,
        status: TermStatus | None = None,
        lang: str | None = None,
        order: TermOrder = "score",
        limit: int = 100,
        offset: int = 0,
    ) -> TermPage:
        c = lexicon_terms.c
        where: list[Any] = []
        if kind is not None:
            where.append(c.kind == kind.value)
        if status is not None:
            where.append(c.status == status.value)
        if lang is not None:
            where.append(c.lang == lang)
        page = (
            select(lexicon_terms)
            .where(*where)
            .order_by(*_ORDERS[order], *_TIEBREAK)
            .limit(limit)
            .offset(offset)
        )
        count = select(func.count()).select_from(lexicon_terms).where(*where)
        async with self._engine.connect() as conn:
            rows = (await conn.execute(page)).mappings().all()
            total = (await conn.execute(count)).scalar_one()
        return TermPage(
            items=[_to_term(row) for row in rows], total=int(total), limit=limit, offset=offset
        )

    async def summary(self) -> LexiconSummary:
        c = lexicon_terms.c
        grouped = select(c.status, c.kind, func.count()).group_by(c.status, c.kind)
        labels = select(func.count()).select_from(message_labels)
        async with self._engine.connect() as conn:
            revision = await self._state(conn, REVISION)
            applied = {
                stage: await self._state(conn, _APPLIED_PREFIX + stage)
                for stage in STAGE_LEXICON_KINDS
            }
            rows = (await conn.execute(grouped)).all()
            label_count = (await conn.execute(labels)).scalar_one()
        by_status = {status.value: 0 for status in TermStatus}
        by_kind = {kind.value: {status.value: 0 for status in TermStatus} for kind in LexiconKind}
        for status, kind, count in rows:
            by_status[status] += count
            by_kind.setdefault(kind, {})[status] = count
        return LexiconSummary(
            revision=revision,
            applied=applied,
            pending_apply=any(value < revision for value in applied.values()),
            by_status=by_status,
            by_kind=by_kind,
            labels=int(label_count),
        )

    # ------------------------------------------------------------------- write

    async def seed(self, terms: Sequence[LexiconTerm]) -> int:
        async with self._engine.begin() as conn:
            known = await self._state_exists(conn, REVISION)
            if not known:
                await conn.execute(insert(lexicon_state).values(name=REVISION, value=1))
            revision = await self._state(conn, REVISION)
            inserted_active = False
            inserted = 0
            for term in {t.key: t for t in terms}.values():
                row = _term_values(term) | {"revision": revision}
                if (await conn.execute(self._insert_ignore(row))).rowcount:
                    inserted += 1
                    inserted_active = inserted_active or term.status is TermStatus.ACTIVE
            if known and inserted_active:
                await self._bump(conn)
        return inserted

    @staticmethod
    async def _state_exists(conn: AsyncConnection, name: str) -> bool:
        stmt = select(lexicon_state.c.name).where(lexicon_state.c.name == name)
        return (await conn.execute(stmt)).first() is not None

    def _insert_ignore(self, values: dict[str, Any]) -> Any:
        if self._dialect == "postgresql":
            return postgresql.insert(lexicon_terms).values(values).on_conflict_do_nothing()
        if self._dialect == "sqlite":
            return sqlite.insert(lexicon_terms).values(values).on_conflict_do_nothing()
        raise NotImplementedError(f"insert-or-ignore is not implemented for {self._dialect!r}")

    async def upsert_candidates(self, terms: Sequence[LexiconTerm]) -> tuple[int, int]:
        unique = list({term.key: term for term in terms}.values())
        inserted = refreshed = 0
        async with self._engine.begin() as conn:
            active_added = False
            for batch in chunks(unique, _KEY_CHUNK):
                stmt = select(
                    lexicon_terms.c.kind, lexicon_terms.c.lang, lexicon_terms.c.term
                ).where(_key_filter([t.key for t in batch]))
                existing = {
                    (LexiconKind(k), lang, term)
                    for k, lang, term in (await conn.execute(stmt)).all()
                }
                for term in batch:
                    values = _term_values(term)
                    if term.key in existing:
                        stats = {name: values[name] for name in _STATS_COLUMNS}
                        await conn.execute(
                            update(lexicon_terms).where(_key_where(term.key)).values(**stats)
                        )
                        refreshed += 1
                    else:
                        await conn.execute(insert(lexicon_terms).values(values))
                        inserted += 1
                        active_added = active_added or term.status is TermStatus.ACTIVE
            if active_added:
                await self._bump(conn)
        return inserted, refreshed

    async def decide(
        self,
        kind: LexiconKind,
        lang: str,
        term: str,
        decision: TermDecision,
        *,
        by: str,
        note: str | None = None,
    ) -> LexiconTerm:
        async with self._engine.begin() as conn:
            row = (
                (await conn.execute(select(lexicon_terms).where(_key_where((kind, lang, term)))))
                .mappings()
                .first()
            )
            if row is None:
                raise KeyError((kind.value, lang, term))
            old = TermStatus(row["status"])
            new = next_status(decision)
            if changes_active_set(old, new):
                revision = await self._bump(conn)
            else:
                revision = await self._state(conn, REVISION)
            values = {
                "status": new.value,
                "decided_at": datetime.now(UTC),
                "decided_by": by,
                "note": note,
                "revision": revision,
            }
            await conn.execute(
                update(lexicon_terms).where(_key_where((kind, lang, term))).values(**values)
            )
            decided = (
                (await conn.execute(select(lexicon_terms).where(_key_where((kind, lang, term)))))
                .mappings()
                .one()
            )
        return _to_term(decided)

    async def add_term(self, term: LexiconTerm) -> LexiconTerm:
        async with self._engine.begin() as conn:
            existing = (
                (await conn.execute(select(lexicon_terms).where(_key_where(term.key))))
                .mappings()
                .first()
            )
            if existing is not None:
                return _to_term(existing)
            values = _term_values(term)
            if term.status is TermStatus.ACTIVE:
                values["revision"] = await self._bump(conn)
            await conn.execute(insert(lexicon_terms).values(values))
            stored = (
                (await conn.execute(select(lexicon_terms).where(_key_where(term.key))))
                .mappings()
                .one()
            )
        return _to_term(stored)

    async def mark_dormant(
        self, *, last_seen_before: datetime, sources: Sequence[TermSource]
    ) -> int:
        if not sources:
            return 0
        c = lexicon_terms.c
        where = (
            (c.status == TermStatus.ACTIVE.value)
            & c.source.in_([s.value for s in sources])
            & c.last_seen.is_not(None)
            & (c.last_seen < last_seen_before)
        )
        async with self._engine.begin() as conn:
            count = (
                await conn.execute(select(func.count()).select_from(lexicon_terms).where(where))
            ).scalar_one()
            if not count:
                return 0
            revision = await self._bump(conn)
            await conn.execute(
                update(lexicon_terms)
                .where(where)
                .values(status=TermStatus.DORMANT.value, revision=revision)
            )
        return int(count)


class SqlLabelRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._dialect = engine.dialect.name

    async def save_label(self, label: MessageLabel) -> None:
        values = {
            "source": label.source.value,
            "chat_id": label.chat_id,
            "msg_id": label.msg_id,
            "is_noise": label.is_noise,
            "reason": label.reason,
            "is_question": label.is_question,
            "created_at": label.created_at,
            "by": label.by,
        }
        update_columns = ("is_noise", "reason", "is_question", "created_at", "by")
        async with self._engine.begin() as conn:
            await conn.execute(upsert(self._dialect, message_labels, update_columns), values)

    async def list_labels(self, limit: int | None = None) -> list[MessageLabel]:
        c = message_labels.c
        stmt = select(message_labels).order_by(
            c.created_at.desc(), c.source, c.chat_id, c.msg_id.desc()
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return [_to_label(row) for row in rows]

    async def count_labels(self) -> int:
        async with self._engine.connect() as conn:
            return int(
                (await conn.execute(select(func.count()).select_from(message_labels))).scalar_one()
            )


def _to_label(row: RowMapping) -> MessageLabel:
    return MessageLabel(
        source=row["source"],
        chat_id=row["chat_id"],
        msg_id=row["msg_id"],
        is_noise=row["is_noise"],
        reason=row["reason"],
        is_question=row["is_question"],
        created_at=row["created_at"],
        by=row["by"],
    )
