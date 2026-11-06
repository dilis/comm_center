"""Refresh tokens, so logout and rotation can revoke them.

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "refresh_token",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("jti", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"),
                  nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_refresh_token_user_id"),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_token"),
        sa.UniqueConstraint("jti", name="uq_refresh_token_jti"),
    )
    op.create_index("ix_refresh_token_user_id", "refresh_token", ["user_id"])


def downgrade() -> None:
    op.drop_table("refresh_token")
