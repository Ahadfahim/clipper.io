"""campaign.link_status: did the campaign's page open the last time Clipper read it

Revision ID: 0004_campaign_link_status
Revises: 0003_attention
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import clipper.db.types

revision: str = "0004_campaign_link_status"
down_revision: str | None = "0003_attention"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("campaign") as batch:
        batch.add_column(sa.Column("link_status", sa.String(), nullable=False, server_default="unknown"))
        batch.add_column(sa.Column("link_checked_at", clipper.db.types.UTCDateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("campaign") as batch:
        batch.drop_column("link_checked_at")
        batch.drop_column("link_status")
