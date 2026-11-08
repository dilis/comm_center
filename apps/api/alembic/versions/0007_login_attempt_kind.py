"""Tell apart what a failed attempt was aimed at (sign-in, password change, token refresh).

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "login_attempt",
        sa.Column("kind", sa.String(length=16), server_default="login", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("login_attempt", "kind")
