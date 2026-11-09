"""Remember which running copy of a worker made the latest session, so a heartbeat is told apart
from a restart (a restart fails what the old copy was sending; a heartbeat must not).

Revision ID: 0012
Revises: 0011
"""
import sqlalchemy as sa

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("worker_account", sa.Column("instance_id", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("worker_account", "instance_id")
