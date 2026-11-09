"""Worker accounts, and a provider, config and worker on each device (SPECS.md 4.7).

``serial_port`` stays until the in-process worker is replaced, then it moves into ``config``.

Revision ID: 0010
Revises: 0009
"""
import sqlalchemy as sa

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "worker_account",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("secret_hash", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=True),
        sa.Column("protocol_version", sa.Integer(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(),
                  server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
                  nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name="fk_worker_account_owner_id"),
        sa.PrimaryKeyConstraint("id", name="pk_worker_account"),
        sa.UniqueConstraint("name", name="uq_worker_account_name"),
    )
    op.add_column("gsm_device", sa.Column(
        "provider", sa.Enum("fake", "android", "gsm_modem", name="gsm_device_provider"),
        server_default="fake", nullable=False))
    op.add_column("gsm_device", sa.Column(
        "config", sa.JSON(), server_default=sa.text("(JSON_OBJECT())"), nullable=False))
    op.add_column("gsm_device", sa.Column("worker_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key("fk_gsm_device_worker_id", "gsm_device", "worker_account",
                          ["worker_id"], ["id"])
    op.create_index("ix_gsm_device_worker_id", "gsm_device", ["worker_id"])


def downgrade() -> None:
    op.drop_constraint("fk_gsm_device_worker_id", "gsm_device", type_="foreignkey")
    op.drop_index("ix_gsm_device_worker_id", table_name="gsm_device")
    op.drop_column("gsm_device", "worker_id")
    op.drop_column("gsm_device", "config")
    op.drop_column("gsm_device", "provider")
    op.drop_table("worker_account")
