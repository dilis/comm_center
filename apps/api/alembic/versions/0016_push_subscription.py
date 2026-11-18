"""Web Push subscriptions: the browsers staff allowed to show notifications.

Revision ID: 0016
Revises: 0015
"""
import sqlalchemy as sa

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "push_subscription",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("endpoint_hash", sa.String(length=64), nullable=False),
        sa.Column("p256dh", sa.String(length=255), nullable=False),
        sa.Column("auth", sa.String(length=255), nullable=False),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"),
                  nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_push_subscription_user_id"),
        sa.PrimaryKeyConstraint("id", name="pk_push_subscription"),
        sa.UniqueConstraint("endpoint_hash", name="uq_push_subscription_endpoint_hash"),
    )
    op.create_index("ix_push_subscription_user_id", "push_subscription", ["user_id"])


def downgrade() -> None:
    op.drop_table("push_subscription")
