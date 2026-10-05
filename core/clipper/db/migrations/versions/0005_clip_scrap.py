"""clip.scrapped_*: throw a clip away (restorable until its files are purged); clip.hidden; moment.scrapped

Revision ID: 0005_clip_scrap
Revises: 0004_campaign_link_status
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import clipper.db.types

revision: str = "0005_clip_scrap"
down_revision: str | None = "0004_campaign_link_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("clip") as batch:
        batch.add_column(sa.Column("scrapped_at", clipper.db.types.UTCDateTime(), nullable=True))
        batch.add_column(sa.Column("scrapped_by", sa.String(), nullable=True))
        batch.add_column(sa.Column("scrap_reason", sa.String(), nullable=True))
        batch.add_column(sa.Column("scrap_json", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("files_purged_at", clipper.db.types.UTCDateTime(), nullable=True))
        batch.add_column(sa.Column("hidden", sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table("moment") as batch:
        batch.add_column(sa.Column("scrapped", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("moment") as batch:
        batch.drop_column("scrapped")
    with op.batch_alter_table("clip") as batch:
        batch.drop_column("hidden")
        batch.drop_column("files_purged_at")
        batch.drop_column("scrap_json")
        batch.drop_column("scrap_reason")
        batch.drop_column("scrapped_by")
        batch.drop_column("scrapped_at")
