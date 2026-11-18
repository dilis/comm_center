"""Push outbox: notifications waiting to be sent, one pending row per subscription.

Revision ID: 0017
Revises: 0016
"""
import sqlalchemy as sa

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "push_outbox",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("subscription_id", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(length=8), server_default="pending", nullable=False),
        sa.Column("pending_key", sa.BigInteger(),
                  sa.Computed("IF(state = 'pending', subscription_id, NULL)", persisted=False),
                  nullable=True),
        sa.Column("message_count", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("last_message_id", sa.BigInteger(), nullable=True),
        sa.Column("senders", sa.JSON(), nullable=False),
        sa.Column("send_after", sa.DateTime(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("lease_until", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"),
                  nullable=False),
        sa.CheckConstraint("state IN ('pending', 'sending')", name=op.f("ck_push_outbox_state")),
        sa.ForeignKeyConstraint(["subscription_id"], ["push_subscription.id"],
                                name="fk_push_outbox_subscription_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_push_outbox"),
        sa.UniqueConstraint("pending_key", name="uq_push_outbox_pending_key"),
    )
    op.create_index("ix_push_outbox_state_send_after", "push_outbox", ["state", "send_after"])
    op.create_index("ix_push_outbox_subscription_id", "push_outbox", ["subscription_id"])


def downgrade() -> None:
    op.drop_table("push_outbox")
