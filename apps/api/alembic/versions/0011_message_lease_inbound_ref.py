"""Message leases (a worker's hold on a message it is sending) and inbound references (so a
retried inbound message is stored once). See SPECS.md 4.7.

Revision ID: 0011
Revises: 0010
"""
import sqlalchemy as sa

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "message_lease",
        sa.Column("message_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("worker_id", sa.BigInteger(), nullable=False),
        sa.Column("device_id", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], name="fk_message_lease_message_id"),
        sa.ForeignKeyConstraint(["worker_id"], ["worker_account.id"], name="fk_message_lease_worker_id"),
        sa.ForeignKeyConstraint(["device_id"], ["gsm_device.id"], name="fk_message_lease_device_id"),
        sa.PrimaryKeyConstraint("message_id", name="pk_message_lease"),
    )
    op.create_index("ix_message_lease_expires_at", "message_lease", ["expires_at"])
    op.create_table(
        "inbound_ref",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("device_id", sa.BigInteger(), nullable=False),
        sa.Column("ref", sa.String(length=255), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"),
                  nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["gsm_device.id"], name="fk_inbound_ref_device_id"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], name="fk_inbound_ref_message_id"),
        sa.PrimaryKeyConstraint("id", name="pk_inbound_ref"),
        sa.UniqueConstraint("device_id", "ref", name="uq_inbound_ref_device_id_ref"),
    )


def downgrade() -> None:
    op.drop_table("inbound_ref")
    op.drop_table("message_lease")
