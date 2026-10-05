"""attention: what you did about a Needs you item (snoozed or dismissed)

Revision ID: 0003_attention
Revises: 0002_session_model
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import clipper.db.types

revision: str = "0003_attention"
down_revision: str | None = "0002_session_model"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "attention",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("snoozed_until", clipper.db.types.UTCDateTime(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("by", sa.String(), nullable=True),
        sa.Column("updated_at", clipper.db.types.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("attention")
