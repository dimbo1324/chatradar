"""SQL implementation of `ChatRepository`, `MessageRepository` and `QueryRepository`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import bindparam, case, delete, func, or_, select, update

from chatradar.domain.models import (
    ChatInfo,
    ChatSummary,
    MessagePage,
    PipelineStats,
    Source,
    StageStat,
    SyncState,
    ThreadDetail,
    UpsertResult,
)
from chatradar.pipeline.base import STAGE_COLUMNS, STAGE_ORDER, later_stages
from chatradar.storage.db import tables as t_
from chatradar.storage.db.rows import (
    MESSAGE_FIELDS,
    STAGE_VALUE_COLUMNS,
    chunks,
    key_in,
    message_values,
    thread_values,
    to_chat,
    to_stored,
    to_thread,
    upsert,
    version_column,
)
from chatradar.storage.db.tables import chats, messages, sync_state, threads

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy import ColumnElement, Executable, RowMapping
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

    from chatradar.domain.models import (
        Message,
        MessageFilter,
        MessageKey,
        ResultValue,
        StageResult,
        StoredMessage,
        Thread,
    )

_MESSAGE_ORDER = (messages.c.source, messages.c.chat_id, messages.c.date, messages.c.msg_id)
_NOT_NOISE = messages.c.is_noise.is_not(True)

_CLEARED: dict[str, Any] = {
    **dict.fromkeys(STAGE_VALUE_COLUMNS),
    **dict.fromkeys(f"{stage}_v" for stage in STAGE_ORDER),
}
"""What a changed message loses: every stage result and every stage version."""

_UPSERT_UPDATE: tuple[str, ...] = (
    *(name for name in MESSAGE_FIELDS if name not in ("source", "chat_id", "msg_id")),
    *_CLEARED,
    "normalize_v",
)


def _pipeline_stage(stage: str) -> str:
    if stage not in STAGE_ORDER:
        raise ValueError(f"unknown pipeline stage {stage!r}; expected one of {STAGE_ORDER}")
    return stage


def _column_value(column: str, value: ResultValue) -> Any:
    if column == "urls":
        if value is None:
            return []
        if not isinstance(value, list):
            raise TypeError(f"urls must be a list of strings, got {type(value).__name__}")
        return [str(url) for url in value]
    return value


class SqlRepository:
    """One object for the three repository ports; SQLite and Postgres through SQLAlchemy."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._dialect = engine.dialect.name

    # ------------------------------------------------------------------ chats

    async def upsert_chats(self, chats: Sequence[ChatInfo]) -> None:
        if not chats:
            return
        rows = [
            {**chat.model_dump(), "source": chat.source.value, "kind": chat.kind.value}
            for chat in chats
        ]
        stmt = upsert(self._dialect, t_.chats, ("title", "username", "kind"))
        async with self._engine.begin() as conn:
            await conn.execute(stmt, rows)

    async def get_chat(self, source: Source, chat_id: str) -> ChatInfo | None:
        stmt = select(chats).where(chats.c.source == source.value, chats.c.chat_id == chat_id)
        async with self._engine.connect() as conn:
            row = (await conn.execute(stmt)).mappings().first()
        return to_chat(row) if row is not None else None

    async def list_chats(self) -> list[ChatInfo]:
        stmt = select(chats).order_by(chats.c.source, chats.c.chat_id)
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return [to_chat(row) for row in rows]

    async def get_sync_state(self, source: Source, chat_id: str) -> SyncState | None:
        stmt = select(sync_state).where(
            sync_state.c.source == source.value, sync_state.c.chat_id == chat_id
        )
        async with self._engine.connect() as conn:
            row = (await conn.execute(stmt)).mappings().first()
        if row is None:
            return None
        return SyncState(
            source=row["source"],
            chat_id=row["chat_id"],
            last_id=row["last_id"],
            last_sync_at=row["last_sync_at"],
        )

    async def set_sync_state(self, state: SyncState) -> None:
        stmt = upsert(self._dialect, sync_state, ("last_id", "last_sync_at"))
        async with self._engine.begin() as conn:
            await conn.execute(stmt, [{**state.model_dump(), "source": state.source.value}])

    # ------------------------------------------------------------------ messages (write)

    async def upsert_many(
        self, messages: Sequence[Message], normalize_version: int
    ) -> UpsertResult:
        unique = {message.key: message for message in messages}
        if not unique:
            return UpsertResult()
        keys = list(unique)
        inserted = updated = unchanged = 0
        stmt = upsert(self._dialect, t_.messages, _UPSERT_UPDATE)
        async with self._engine.begin() as conn:
            for part in chunks(keys):
                found = await conn.execute(
                    select(
                        t_.messages.c.source,
                        t_.messages.c.chat_id,
                        t_.messages.c.msg_id,
                        t_.messages.c.content_hash,
                    ).where(key_in(part))
                )
                existing = {(Source(r[0]), r[1], r[2]): r[3] for r in found}
                rows: list[dict[str, Any]] = []
                for key in part:
                    message = unique[key]
                    old_hash = existing.get(key)
                    if old_hash == message.content_hash:
                        unchanged += 1
                        continue
                    if old_hash is None:
                        inserted += 1
                    else:
                        updated += 1
                    rows.append(
                        {**message_values(message), **_CLEARED, "normalize_v": normalize_version}
                    )
                if rows:
                    await conn.execute(stmt, rows)
        return UpsertResult(inserted=inserted, updated=updated, unchanged=unchanged)

    async def pending_for(
        self, stage: str, version: int, depends_on: str | None, limit: int
    ) -> list[StoredMessage]:
        column = messages.c[version_column(stage)]
        conditions: list[ColumnElement[bool]] = [or_(column.is_(None), column < version)]
        if depends_on is not None:
            conditions.append(messages.c[version_column(depends_on)].is_not(None))
        stmt = select(messages).where(*conditions).order_by(*_MESSAGE_ORDER).limit(limit)
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return [to_stored(row) for row in rows]

    async def mark(self, stage: str, version: int, results: Sequence[StageResult]) -> None:
        allowed = STAGE_COLUMNS[_pipeline_stage(stage)]
        groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
        for result in results:
            forbidden = sorted(set(result.values) - set(allowed))
            if forbidden:
                raise ValueError(f"stage {stage!r} may not write {forbidden}")
            columns = tuple(sorted(result.values))
            params: dict[str, Any] = {
                "k_source": str(result.key[0]),
                "k_chat_id": result.key[1],
                "k_msg_id": result.key[2],
            }
            params.update({f"v_{c}": _column_value(c, v) for c, v in result.values.items()})
            groups.setdefault(columns, []).append(params)
        if not groups:
            return
        fixed: dict[str, Any] = {
            f"{stage}_v": version,
            **dict.fromkeys(f"{later}_v" for later in later_stages(stage)),
        }
        async with self._engine.begin() as conn:
            for columns, rows in groups.items():
                stmt = (
                    update(messages)
                    .where(
                        messages.c.source == bindparam("k_source"),
                        messages.c.chat_id == bindparam("k_chat_id"),
                        messages.c.msg_id == bindparam("k_msg_id"),
                    )
                    .values({**{c: bindparam(f"v_{c}") for c in columns}, **fixed})
                )
                await conn.execute(stmt, rows)

    async def get_many(self, keys: Sequence[MessageKey]) -> dict[MessageKey, StoredMessage]:
        found: dict[MessageKey, StoredMessage] = {}
        async with self._engine.connect() as conn:
            for part in chunks(list(dict.fromkeys(keys))):
                rows = (await conn.execute(select(messages).where(key_in(part)))).mappings()
                for row in rows:
                    message = to_stored(row)
                    found[message.key] = message
        return found

    async def chat_window(
        self, source: Source, chat_id: str, since: datetime
    ) -> list[StoredMessage]:
        stmt = (
            select(messages)
            .where(
                messages.c.source == source.value,
                messages.c.chat_id == chat_id,
                messages.c.date >= since,
            )
            .order_by(messages.c.date, messages.c.msg_id)
        )
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return [to_stored(row) for row in rows]

    async def save_threads(
        self, source: Source, chat_id: str, since: datetime, threads: Sequence[Thread]
    ) -> None:
        for thread in threads:
            if thread.source != source or thread.chat_id != chat_id:
                raise ValueError(f"thread {thread.thread_id!r} is not in chat {chat_id!r}")
        stmt = upsert(
            self._dialect,
            t_.threads,
            (c.name for c in t_.threads.columns if c.name != "thread_id"),
        )
        async with self._engine.begin() as conn:
            await conn.execute(
                delete(t_.threads).where(
                    t_.threads.c.source == source.value,
                    t_.threads.c.chat_id == chat_id,
                    t_.threads.c.started_at >= since,
                )
            )
            if threads:
                await conn.execute(stmt, [thread_values(thread) for thread in threads])

    async def reset_stage(self, stage: str) -> int:
        names = [f"{s}_v" for s in (_pipeline_stage(stage), *later_stages(stage))]
        stmt = (
            update(messages)
            .where(or_(*(messages.c[name].is_not(None) for name in names)))
            .values(dict.fromkeys(names))
        )
        async with self._engine.begin() as conn:
            result = await conn.execute(stmt)
        return result.rowcount

    async def clear_derived(self) -> None:
        async with self._engine.begin() as conn:
            if conn.dialect.name == "sqlite":
                await conn.exec_driver_sql("DELETE FROM threads_fts")
            await conn.execute(delete(threads))
            await conn.execute(delete(messages))

    # ------------------------------------------------------------------ read side

    async def chat_summaries(self) -> list[ChatSummary]:
        message_stats = select(
            messages.c.source,
            messages.c.chat_id,
            func.count().label("message_count"),
            func.coalesce(func.sum(case((messages.c.is_noise.is_(True), 1), else_=0)), 0).label(
                "noise_count"
            ),
            func.min(messages.c.date).label("first_message_at"),
            func.max(messages.c.date).label("last_message_at"),
        ).group_by(messages.c.source, messages.c.chat_id)
        thread_stats = select(
            threads.c.source, threads.c.chat_id, func.count().label("thread_count")
        ).group_by(threads.c.source, threads.c.chat_id)
        async with self._engine.connect() as conn:
            chat_rows = (await conn.execute(select(chats))).mappings().all()
            stats = {(r["source"], r["chat_id"]): r for r in await _mappings(conn, message_stats)}
            thread_counts = {
                (r["source"], r["chat_id"]): r["thread_count"]
                for r in await _mappings(conn, thread_stats)
            }
            syncs = {
                (r["source"], r["chat_id"]): r["last_sync_at"]
                for r in await _mappings(conn, select(sync_state))
            }
        known = {(r["source"], r["chat_id"]): to_chat(r) for r in chat_rows}
        for key in stats.keys() - known.keys():
            known[key] = ChatInfo(source=Source(key[0]), chat_id=key[1], title=key[1])
        summaries: list[ChatSummary] = []
        for key in sorted(known):
            row = stats.get(key)
            summaries.append(
                ChatSummary(
                    chat=known[key],
                    message_count=row["message_count"] if row else 0,
                    noise_count=row["noise_count"] if row else 0,
                    thread_count=thread_counts.get(key, 0),
                    first_message_at=row["first_message_at"] if row else None,
                    last_message_at=row["last_message_at"] if row else None,
                    last_sync_at=syncs.get(key),
                )
            )
        return summaries

    async def pipeline_stats(self, stage_versions: Sequence[tuple[str, int]]) -> PipelineStats:
        columns: list[ColumnElement[Any]] = [func.count().label("total")]
        for index, (stage, version) in enumerate(stage_versions):
            column = messages.c[version_column(stage)]
            columns.append(_count_if(column == version).label(f"done_{index}"))
            columns.append(
                _count_if(or_(column.is_(None), column < version)).label(f"pending_{index}")
            )
        async with self._engine.connect() as conn:
            row = (await conn.execute(select(*columns).select_from(messages))).mappings().one()
        return PipelineStats(
            total_messages=row["total"],
            stages=[
                StageStat(
                    stage=stage,
                    version=version,
                    done=row[f"done_{index}"],
                    pending=row[f"pending_{index}"],
                )
                for index, (stage, version) in enumerate(stage_versions)
            ],
        )

    async def list_messages(self, filters: MessageFilter) -> MessagePage:
        where = _message_conditions(filters)
        page = (
            select(messages)
            .where(*where)
            .order_by(messages.c.date.desc(), messages.c.msg_id.desc())
            .limit(filters.limit)
            .offset(filters.offset)
        )
        count = select(func.count()).select_from(messages).where(*where)
        async with self._engine.connect() as conn:
            total = (await conn.execute(count)).scalar_one()
            rows = (await conn.execute(page)).mappings().all()
        return MessagePage(
            items=[to_stored(row) for row in rows],
            total=total,
            limit=filters.limit,
            offset=filters.offset,
        )

    async def get_thread(self, thread_id: str) -> ThreadDetail | None:
        members = (
            select(messages)
            .where(messages.c.thread_id == thread_id, _NOT_NOISE)
            .order_by(messages.c.date, messages.c.msg_id)
        )
        async with self._engine.connect() as conn:
            head = (
                (await conn.execute(select(threads).where(threads.c.thread_id == thread_id)))
                .mappings()
                .first()
            )
            if head is None:
                return None
            rows = (await conn.execute(members)).mappings().all()
        return ThreadDetail(thread=to_thread(head), messages=[to_stored(row) for row in rows])

    async def sample(self, *, is_noise: bool, n: int) -> list[StoredMessage]:
        stmt = (
            select(messages)
            .where(messages.c.is_noise.is_(True) if is_noise else messages.c.is_noise.is_(False))
            .order_by(func.random())
            .limit(n)
        )
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return [to_stored(row) for row in rows]

    async def noise_reasons(self) -> dict[str, int]:
        count = func.count().label("n")
        stmt = (
            select(messages.c.noise_reason, count)
            .where(messages.c.is_noise.is_(True), messages.c.noise_reason.is_not(None))
            .group_by(messages.c.noise_reason)
            .order_by(count.desc(), messages.c.noise_reason)
        )
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).all()
        return {str(reason): int(n) for reason, n in rows}


def _count_if(condition: ColumnElement[bool]) -> ColumnElement[Any]:
    return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)


def _message_conditions(filters: MessageFilter) -> list[ColumnElement[bool]]:
    c = messages.c
    where: list[ColumnElement[bool]] = []
    if filters.source is not None:
        where.append(c.source == filters.source.value)
    if filters.chat_id is not None:
        where.append(c.chat_id == filters.chat_id)
    if filters.date_from is not None:
        where.append(c.date >= filters.date_from)
    if filters.date_to is not None:
        where.append(c.date <= filters.date_to)
    if filters.lang is not None:
        where.append(c.lang == filters.lang)
    if filters.is_noise is not None:
        where.append(c.is_noise.is_(filters.is_noise))
    if filters.noise_reason is not None:
        where.append(c.noise_reason == filters.noise_reason)
    if filters.is_question is not None:
        where.append(c.is_question.is_(filters.is_question))
    if filters.thread_id is not None:
        where.append(c.thread_id == filters.thread_id)
    return where


async def _mappings(conn: AsyncConnection, stmt: Executable) -> Sequence[RowMapping]:
    return (await conn.execute(stmt)).mappings().all()
