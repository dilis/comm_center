"""A worker is its device's system agent: drop ``worker_account`` (SPECS.md 4.7).

The secret moves to the agent's ``password_hash`` (a system agent still cannot log in to the web
app: ``login_enabled`` stays 0), what the worker reported in its session moves to ``gsm_device``,
and everything about *how* to reach a device (``serial_port``, ``provider``, ``config``) leaves
the database: it is the worker program's own configuration.

A worker now signs in as the agent of the device it serves (``gsm-<name>``), so a worker that
served several devices is split: each device's agent gets the old secret.

Revision ID: 0014
Revises: 0013
"""
import sqlalchemy as sa

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

OLD_CHECK = "is_system = 0 OR (login_enabled = 0 AND password_hash IS NULL)"
NEW_CHECK = "is_system = 0 OR login_enabled = 0"
CK = op.f("ck_users_system_agent_cannot_log_in")


def upgrade() -> None:
    op.drop_constraint(CK, "users", type_="check")
    op.create_check_constraint(CK, "users", NEW_CHECK)

    op.add_column("gsm_device", sa.Column("version", sa.String(length=64), nullable=True))
    op.add_column("gsm_device", sa.Column("protocol_version", sa.Integer(), nullable=True))
    op.add_column("gsm_device", sa.Column("instance_id", sa.String(length=64), nullable=True))
    op.add_column("gsm_device", sa.Column("last_seen_at", sa.DateTime(), nullable=True))

    # Carry over each device's worker: its secret to the device's agent, its session to the device.
    op.execute(
        "UPDATE users u JOIN gsm_device d ON d.agent_user_id = u.id "
        "JOIN worker_account w ON w.id = d.worker_id "
        "SET u.password_hash = w.secret_hash WHERE w.deleted_at IS NULL"
    )
    op.execute(
        "UPDATE gsm_device d JOIN worker_account w ON w.id = d.worker_id "
        "SET d.version = w.version, d.protocol_version = w.protocol_version, "
        "d.instance_id = w.instance_id, d.last_seen_at = w.last_seen_at"
    )

    op.drop_constraint("fk_message_lease_worker_id", "message_lease", type_="foreignkey")
    op.drop_column("message_lease", "worker_id")
    op.drop_constraint("fk_gsm_device_worker_id", "gsm_device", type_="foreignkey")
    op.drop_index("ix_gsm_device_worker_id", table_name="gsm_device")
    op.drop_column("gsm_device", "worker_id")
    op.drop_column("gsm_device", "config")
    op.drop_column("gsm_device", "provider")
    op.drop_column("gsm_device", "serial_port")
    op.drop_table("worker_account")


def downgrade() -> None:
    op.create_table(
        "worker_account",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("secret_hash", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=True),
        sa.Column("protocol_version", sa.Integer(), nullable=True),
        sa.Column("instance_id", sa.String(length=64), nullable=True),
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
    op.add_column("gsm_device", sa.Column("serial_port", sa.String(length=255), nullable=False,
                                          server_default="-"))
    op.add_column("gsm_device", sa.Column(
        "provider", sa.Enum("fake", "android", "gsm_modem", name="gsm_device_provider"),
        server_default="fake", nullable=False))
    op.add_column("gsm_device", sa.Column(
        "config", sa.JSON(), server_default=sa.text("(JSON_OBJECT())"), nullable=False))
    op.add_column("gsm_device", sa.Column("worker_id", sa.BigInteger(), nullable=True))

    # One worker per device that had a secret, named after the agent.
    op.execute(
        "INSERT INTO worker_account (name, secret_hash, version, protocol_version, instance_id, "
        "last_seen_at, owner_id) "
        "SELECT u.username, u.password_hash, d.version, d.protocol_version, d.instance_id, "
        "d.last_seen_at, d.owner_id FROM gsm_device d JOIN users u ON u.id = d.agent_user_id "
        "WHERE u.password_hash IS NOT NULL"
    )
    op.execute(
        "UPDATE gsm_device d JOIN users u ON u.id = d.agent_user_id "
        "JOIN worker_account w ON w.name = u.username SET d.worker_id = w.id"
    )
    op.create_foreign_key("fk_gsm_device_worker_id", "gsm_device", "worker_account",
                          ["worker_id"], ["id"])
    op.create_index("ix_gsm_device_worker_id", "gsm_device", ["worker_id"])

    op.add_column("message_lease", sa.Column("worker_id", sa.BigInteger(), nullable=True))
    op.execute(
        "UPDATE message_lease l JOIN gsm_device d ON d.id = l.device_id SET l.worker_id = d.worker_id"
    )
    op.execute("DELETE FROM message_lease WHERE worker_id IS NULL")
    op.alter_column("message_lease", "worker_id", existing_type=sa.BigInteger(), nullable=False)
    op.create_foreign_key("fk_message_lease_worker_id", "message_lease", "worker_account",
                          ["worker_id"], ["id"])

    op.execute("UPDATE users SET password_hash = NULL WHERE is_system = 1")
    op.drop_constraint(CK, "users", type_="check")
    op.create_check_constraint(CK, "users", OLD_CHECK)
    op.drop_column("gsm_device", "last_seen_at")
    op.drop_column("gsm_device", "instance_id")
    op.drop_column("gsm_device", "protocol_version")
    op.drop_column("gsm_device", "version")
