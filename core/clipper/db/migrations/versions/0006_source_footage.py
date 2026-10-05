"""source.waiting_since / source.reason: footage that needs you (a download that failed, or a host Clipper can't download from)

Revision ID: 0006_source_footage
Revises: 0005_clip_scrap
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import clipper.db.types

revision: str = "0006_source_footage"
down_revision: str | None = "0005_clip_scrap"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("source") as batch:
        batch.add_column(sa.Column("waiting_since", clipper.db.types.UTCDateTime(), nullable=True))
        batch.add_column(sa.Column("reason", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("source") as batch:
        batch.drop_column("reason")
        batch.drop_column("waiting_since")
