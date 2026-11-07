"""Link a reply to the received message it answers.

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("reply_to_id", sa.BigInteger(), nullable=True))
    op.create_index("ix_messages_reply_to_id", "messages", ["reply_to_id"])
    op.create_foreign_key(
        "fk_messages_reply_to_id", "messages", "messages", ["reply_to_id"], ["id"]
    )


def downgrade() -> None:
    op.drop_constraint("fk_messages_reply_to_id", "messages", type_="foreignkey")
    op.drop_index("ix_messages_reply_to_id", table_name="messages")
    op.drop_column("messages", "reply_to_id")
