"""job.progress_at / job.detail (is a job still moving?) and agent_request.waiting_reason (why a request hasn't started)

Revision ID: 0007_stalls
Revises: 0006_source_footage
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import clipper.db.types

revision: str = "0007_stalls"
down_revision: str | None = "0006_source_footage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("job") as batch:
        batch.add_column(sa.Column("progress_at", clipper.db.types.UTCDateTime(), nullable=True))
        batch.add_column(sa.Column("detail", sa.String(), nullable=True))
    with op.batch_alter_table("agent_request") as batch:
        batch.add_column(sa.Column("waiting_reason", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agent_request") as batch:
        batch.drop_column("waiting_reason")
    with op.batch_alter_table("job") as batch:
        batch.drop_column("detail")
        batch.drop_column("progress_at")
