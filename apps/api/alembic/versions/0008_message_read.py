"""Per-user read state of received messages.

Everything received before this migration counts as read for the people who exist now, so the
first sign-in after upgrading is not a wall of "unread".

Revision ID: 0008
Revises: 0007
"""
import sqlalchemy as sa

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "message_read",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("read_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"),
                  nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_message_read_user_id"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], name="fk_message_read_message_id"),
        sa.PrimaryKeyConstraint("user_id", "message_id", name="pk_message_read"),
    )
    op.create_index("ix_message_read_message_id", "message_read", ["message_id"])
    op.execute(
        """
        INSERT INTO message_read (user_id, message_id)
        SELECT u.id, m.id
        FROM users u
        JOIN messages m
        JOIN users a ON a.id = m.owner_id
        WHERE u.is_system = 0 AND a.is_system = 1 AND a.agent_direction = 'inbound'
        """
    )


def downgrade() -> None:
    op.drop_table("message_read")
