"""Let a single message jump ahead of a bulk send in the outbound queue.

``is_bulk`` is set once at creation: true for a bulk send. The claim takes non-bulk messages first
and, within each group, the oldest first, so singles go
out in the order they were posted and the message already being sent is never interrupted.

Revision ID: 0018
Revises: 0017
"""
import sqlalchemy as sa

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("is_bulk", sa.Boolean(), server_default=sa.text("0"), nullable=False),
    )
    # Serves the claim's ORDER BY: without it MySQL sorts, and the sort locks every queued row, so
    # one claimer would starve the others under SKIP LOCKED.
    op.create_index("ix_messages_queue", "messages", ["status", "is_bulk", "created_at", "id"])


def downgrade() -> None:
    op.drop_index("ix_messages_queue", table_name="messages")
    op.drop_column("messages", "is_bulk")
