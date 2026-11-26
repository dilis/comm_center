"""Tie the refresh tokens of one sign-in together, so that signed-in sessions can be listed.

``session_id`` and ``signed_in_at`` are carried over when a token is rotated; ``ip`` and
``user_agent`` are what the browser was last seen as. A token issued before this migration is its
own session, signed in when it was issued (its real sign-in time and device were never stored).

Revision ID: 0019
Revises: 0018
"""
import sqlalchemy as sa

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("refresh_token", sa.Column("session_id", sa.String(32), nullable=True))
    op.add_column("refresh_token", sa.Column("signed_in_at", sa.DateTime(), nullable=True))
    op.add_column("refresh_token", sa.Column("ip", sa.String(45), nullable=True))
    op.add_column("refresh_token", sa.Column("user_agent", sa.String(255), nullable=True))
    op.execute("UPDATE refresh_token SET session_id = jti, signed_in_at = created_at")
    op.alter_column("refresh_token", "session_id", existing_type=sa.String(32), nullable=False)
    op.alter_column(
        "refresh_token",
        "signed_in_at",
        existing_type=sa.DateTime(),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


def downgrade() -> None:
    for column in ("user_agent", "ip", "signed_in_at", "session_id"):
        op.drop_column("refresh_token", column)
