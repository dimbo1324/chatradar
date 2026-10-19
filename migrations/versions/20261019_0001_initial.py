"""initial schema: chats, sync_state, messages, threads, threads_fts

Revision ID: 0001
Revises:
Create Date: 2026-10-19 16:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from chatradar.storage.db.tables import UTCDateTime

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chats",
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("chat_id", sa.String(64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("username", sa.String(64)),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.PrimaryKeyConstraint("source", "chat_id", name="pk_chats"),
    )
    op.create_table(
        "sync_state",
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("chat_id", sa.String(64), nullable=False),
        sa.Column("last_id", sa.String(64)),
        sa.Column("last_sync_at", UTCDateTime()),
        sa.PrimaryKeyConstraint("source", "chat_id", name="pk_sync_state"),
    )
    op.create_table(
        "messages",
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("chat_id", sa.String(64), nullable=False),
        sa.Column("msg_id", sa.String(64), nullable=False),
        sa.Column("author_id", sa.String(64)),
        sa.Column("date", UTCDateTime(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_raw", sa.Text(), nullable=False),
        sa.Column("reply_to", sa.String(64)),
        sa.Column("topic_id", sa.String(64)),
        sa.Column("media_type", sa.String(16), nullable=False),
        sa.Column("is_forward", sa.Boolean(), nullable=False),
        sa.Column("is_service", sa.Boolean(), nullable=False),
        sa.Column("edited_at", UTCDateTime()),
        sa.Column("link", sa.Text()),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("lang", sa.String(16)),
        sa.Column("is_question", sa.Boolean()),
        sa.Column("urls", sa.JSON()),
        sa.Column("has_mention", sa.Boolean()),
        sa.Column("is_noise", sa.Boolean()),
        sa.Column("noise_reason", sa.String(32)),
        sa.Column("thread_id", sa.String(160)),
        sa.Column("normalize_v", sa.Integer()),
        sa.Column("noise_v", sa.Integer()),
        sa.Column("enrich_v", sa.Integer()),
        sa.Column("threads_v", sa.Integer()),
        sa.Column("index_v", sa.Integer()),
        sa.PrimaryKeyConstraint("source", "chat_id", "msg_id", name="pk_messages"),
    )
    op.create_index("ix_messages_chat_date", "messages", ["source", "chat_id", "date"])
    op.create_index("ix_messages_thread_id", "messages", ["thread_id"])
    op.create_index("ix_messages_is_noise", "messages", ["is_noise"])
    op.create_table(
        "threads",
        sa.Column("thread_id", sa.String(160), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("chat_id", sa.String(64), nullable=False),
        sa.Column("topic_id", sa.String(64)),
        sa.Column("root_msg_id", sa.String(64), nullable=False),
        sa.Column("started_at", UTCDateTime(), nullable=False),
        sa.Column("ended_at", UTCDateTime(), nullable=False),
        sa.Column("msg_count", sa.Integer(), nullable=False),
        sa.Column("has_question", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("thread_id", name="pk_threads"),
    )
    op.create_index("ix_threads_chat_started", "threads", ["source", "chat_id", "started_at"])
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            "CREATE VIRTUAL TABLE threads_fts USING fts5("
            "thread_id UNINDEXED, chat_id UNINDEXED, body, "
            "tokenize = 'unicode61 remove_diacritics 2')"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute("DROP TABLE IF EXISTS threads_fts")
    op.drop_index("ix_threads_chat_started", table_name="threads")
    op.drop_table("threads")
    op.drop_index("ix_messages_is_noise", table_name="messages")
    op.drop_index("ix_messages_thread_id", table_name="messages")
    op.drop_index("ix_messages_chat_date", table_name="messages")
    op.drop_table("messages")
    op.drop_table("sync_state")
    op.drop_table("chats")
