"""Row ↔ model mapping and the dialect-specific upsert shared by the repositories."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import tuple_
from sqlalchemy.dialects import postgresql, sqlite

from chatradar.domain.models import ChatInfo, Message, StoredMessage, Thread
from chatradar.pipeline.base import STAGE_COLUMNS, STAGE_ORDER
from chatradar.storage.db.tables import messages

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from sqlalchemy import ColumnElement, RowMapping, Table
    from sqlalchemy.sql.dml import Insert

    from chatradar.domain.models import MessageKey

KEY_CHUNK = 500
"""Keys per `IN` query: well below SQLite's bound-parameter limit (three per key)."""

MESSAGE_FIELDS: tuple[str, ...] = tuple(Message.model_fields)
STAGE_VALUE_COLUMNS: tuple[str, ...] = tuple(c for cols in STAGE_COLUMNS.values() for c in cols)
VERSIONED_STAGES: tuple[str, ...] = ("normalize", *STAGE_ORDER)


def version_column(stage: str) -> str:
    if stage not in VERSIONED_STAGES:
        raise ValueError(f"unknown stage {stage!r}")
    return f"{stage}_v"


def chunks[T](items: Sequence[T], size: int = KEY_CHUNK) -> Iterable[Sequence[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def key_in(keys: Sequence[MessageKey]) -> ColumnElement[bool]:
    return tuple_(messages.c.source, messages.c.chat_id, messages.c.msg_id).in_(
        [(str(source), chat_id, msg_id) for source, chat_id, msg_id in keys]
    )


def upsert(dialect: str, table: Table, update: Iterable[str]) -> Insert:
    """`INSERT ... ON CONFLICT (primary key) DO UPDATE SET <update> = excluded.<update>`."""
    index_elements = [column.name for column in table.primary_key.columns]
    if dialect == "postgresql":
        pg = postgresql.insert(table)
        return pg.on_conflict_do_update(
            index_elements=index_elements, set_={name: pg.excluded[name] for name in update}
        )
    if dialect == "sqlite":
        lite = sqlite.insert(table)
        return lite.on_conflict_do_update(
            index_elements=index_elements, set_={name: lite.excluded[name] for name in update}
        )
    raise NotImplementedError(f"upsert is not implemented for {dialect!r}")


def message_values(message: Message) -> dict[str, Any]:
    values = message.model_dump()
    values["source"] = message.source.value
    values["media_type"] = message.media_type.value
    return values


def to_stored(row: RowMapping) -> StoredMessage:
    data: dict[str, Any] = {name: row[name] for name in MESSAGE_FIELDS}
    data.update({name: row[name] for name in STAGE_VALUE_COLUMNS})
    data["urls"] = tuple(row["urls"] or ())
    data["versions"] = {
        stage: row[f"{stage}_v"] for stage in VERSIONED_STAGES if row[f"{stage}_v"] is not None
    }
    return StoredMessage.model_validate(data)


def to_thread(row: RowMapping) -> Thread:
    return Thread(
        thread_id=row["thread_id"],
        source=row["source"],
        chat_id=row["chat_id"],
        topic_id=row["topic_id"],
        root_msg_id=row["root_msg_id"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        msg_count=row["msg_count"],
        has_question=row["has_question"],
    )


def thread_values(thread: Thread) -> dict[str, Any]:
    values = thread.model_dump()
    values["source"] = thread.source.value
    return values


def to_chat(row: RowMapping) -> ChatInfo:
    return ChatInfo(
        source=row["source"],
        chat_id=row["chat_id"],
        title=row["title"],
        username=row["username"],
        kind=row["kind"],
    )
