"""Failed sign-ins, for login rate limiting.

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "login_attempt",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("ip", sa.String(length=45), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"),
                  nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_login_attempt"),
    )
    op.create_index("ix_login_attempt_username_created_at", "login_attempt",
                    ["username", "created_at"])
    op.create_index("ix_login_attempt_ip_created_at", "login_attempt", ["ip", "created_at"])


def downgrade() -> None:
    op.drop_table("login_attempt")
