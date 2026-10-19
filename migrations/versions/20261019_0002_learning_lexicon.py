"""learning lexicon: lexicon_terms, lexicon_state, message_labels

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-19 19:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from chatradar.storage.db.tables import UTCDateTime

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lexicon_terms",
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("lang", sa.String(16), nullable=False),
        sa.Column("term", sa.String(200), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("occurrences", sa.Integer(), nullable=False),
        sa.Column("chats", sa.Integer(), nullable=False),
        sa.Column("authors", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("examples", sa.JSON()),
        sa.Column("first_seen", UTCDateTime()),
        sa.Column("last_seen", UTCDateTime()),
        sa.Column("decided_at", UTCDateTime()),
        sa.Column("decided_by", sa.String(32)),
        sa.Column("note", sa.Text()),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("kind", "lang", "term", name="pk_lexicon_terms"),
    )
    op.create_index("ix_lexicon_terms_status_kind", "lexicon_terms", ["status", "kind"])
    op.create_index("ix_lexicon_terms_score", "lexicon_terms", ["score"])
    op.create_table(
        "lexicon_state",
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("name", name="pk_lexicon_state"),
    )
    op.create_table(
        "message_labels",
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("chat_id", sa.String(64), nullable=False),
        sa.Column("msg_id", sa.String(64), nullable=False),
        sa.Column("is_noise", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(32)),
        sa.Column("is_question", sa.Boolean()),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("by", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint("source", "chat_id", "msg_id", name="pk_message_labels"),
    )


def downgrade() -> None:
    op.drop_table("message_labels")
    op.drop_table("lexicon_state")
    op.drop_index("ix_lexicon_terms_score", table_name="lexicon_terms")
    op.drop_index("ix_lexicon_terms_status_kind", table_name="lexicon_terms")
    op.drop_table("lexicon_terms")
