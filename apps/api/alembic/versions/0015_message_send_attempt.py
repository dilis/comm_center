"""Count the retries of a failed message, so each one gets its own id on the phone.

The Android gateway refuses an id it already has (409), so a message put back in the queue after a
failure could never be sent again under ``cc-<id>``. ``send_attempt`` is 0 until a person retries
the message; it then names the send ``cc-<id>-<n>``.

Revision ID: 0015
Revises: 0014
"""
import sqlalchemy as sa

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("send_attempt", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("messages", "send_attempt")
