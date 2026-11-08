"""Keep the latest modem error on the device, so it can be shown to people.

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("gsm_device", sa.Column("last_error", sa.String(length=500), nullable=True))
    op.add_column("gsm_device", sa.Column("last_error_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("gsm_device", "last_error_at")
    op.drop_column("gsm_device", "last_error")
