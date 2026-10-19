"""SQLAlchemy Core tables — the database contract. Change only with a migration."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Dialect,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
)
from sqlalchemy.types import TypeDecorator

metadata = MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_N_name)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "pk": "pk_%(table_name)s",
    }
)

FTS_TABLES = ("threads_fts",)
"""Virtual tables created by raw SQL in migrations; Alembic autogenerate ignores them."""


class UTCDateTime(TypeDecorator[datetime]):
    """Stores UTC; always returns timezone-aware UTC datetimes (SQLite drops the zone)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime given to a UTC column")
        return value.astimezone(UTC).replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError(f"unexpected datetime value {value!r}")
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


chats = Table(
    "chats",
    metadata,
    Column("source", String(32), primary_key=True),
    Column("chat_id", String(64), primary_key=True),
    Column("title", Text, nullable=False),
    Column("username", String(64)),
    Column("kind", String(16), nullable=False),
)

sync_state = Table(
    "sync_state",
    metadata,
    Column("source", String(32), primary_key=True),
    Column("chat_id", String(64), primary_key=True),
    Column("last_id", String(64)),
    Column("last_sync_at", UTCDateTime()),
)

messages = Table(
    "messages",
    metadata,
    Column("source", String(32), primary_key=True),
    Column("chat_id", String(64), primary_key=True),
    Column("msg_id", String(64), primary_key=True),
    Column("author_id", String(64)),
    Column("date", UTCDateTime(), nullable=False),
    Column("text", Text, nullable=False),
    Column("text_raw", Text, nullable=False),
    Column("reply_to", String(64)),
    Column("topic_id", String(64)),
    Column("media_type", String(16), nullable=False),
    Column("is_forward", Boolean, nullable=False),
    Column("is_service", Boolean, nullable=False),
    Column("edited_at", UTCDateTime()),
    Column("link", Text),
    Column("content_hash", String(64), nullable=False),
    # enrich
    Column("lang", String(16)),
    Column("is_question", Boolean),
    Column("urls", JSON),
    Column("has_mention", Boolean),
    # noise
    Column("is_noise", Boolean),
    Column("noise_reason", String(32)),
    # threads
    Column("thread_id", String(160)),
    # stage versions
    Column("normalize_v", Integer),
    Column("noise_v", Integer),
    Column("enrich_v", Integer),
    Column("threads_v", Integer),
    Column("index_v", Integer),
    Index("ix_messages_chat_date", "source", "chat_id", "date"),
    Index("ix_messages_thread_id", "thread_id"),
    Index("ix_messages_is_noise", "is_noise"),
)

threads = Table(
    "threads",
    metadata,
    Column("thread_id", String(160), primary_key=True),
    Column("source", String(32), nullable=False),
    Column("chat_id", String(64), nullable=False),
    Column("topic_id", String(64)),
    Column("root_msg_id", String(64), nullable=False),
    Column("started_at", UTCDateTime(), nullable=False),
    Column("ended_at", UTCDateTime(), nullable=False),
    Column("msg_count", Integer, nullable=False),
    Column("has_question", Boolean, nullable=False),
    Index("ix_threads_chat_started", "source", "chat_id", "started_at"),
)


lexicon_terms = Table(
    "lexicon_terms",
    metadata,
    Column("kind", String(32), primary_key=True),
    Column("lang", String(16), primary_key=True),
    Column("term", String(200), primary_key=True),
    Column("status", String(16), nullable=False),
    Column("source", String(16), nullable=False),
    Column("weight", Float(), nullable=False),
    Column("occurrences", Integer, nullable=False),
    Column("chats", Integer, nullable=False),
    Column("authors", Integer, nullable=False),
    Column("score", Float(), nullable=False),
    Column("examples", JSON),
    Column("first_seen", UTCDateTime()),
    Column("last_seen", UTCDateTime()),
    Column("decided_at", UTCDateTime()),
    Column("decided_by", String(32)),
    Column("note", Text),
    Column("revision", Integer, nullable=False),
    Index("ix_lexicon_terms_status_kind", "status", "kind"),
    Index("ix_lexicon_terms_score", "score"),
)

lexicon_state = Table(
    "lexicon_state",
    metadata,
    Column("name", String(32), primary_key=True),  # "revision", "applied:noise", "applied:enrich"
    Column("value", Integer, nullable=False),
)

message_labels = Table(
    "message_labels",
    metadata,
    Column("source", String(32), primary_key=True),
    Column("chat_id", String(64), primary_key=True),
    Column("msg_id", String(64), primary_key=True),
    Column("is_noise", Boolean, nullable=False),
    Column("reason", String(32)),
    Column("is_question", Boolean),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("by", String(32), nullable=False),
)
