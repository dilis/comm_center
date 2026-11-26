"""Remember which session turned notifications on, so that signing the session out stops them.

A subscription made before this migration has no session and is not removed that way.

Revision ID: 0020
Revises: 0019
"""
import sqlalchemy as sa

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("push_subscription", sa.Column("session_id", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("push_subscription", "session_id")
