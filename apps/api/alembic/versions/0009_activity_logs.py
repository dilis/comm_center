"""Activity log (what signed-in people did) and login log (sign-in history), plus who may read them.

The new permission ``logs:read_all`` is held by a ``logs_viewer`` building block that the admin and
auditor roles include.

Revision ID: 0009
Revises: 0008
"""
import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

SYSTEM_USER_ID = 1
ROLES = ("admin", "auditor")


def upgrade() -> None:
    op.create_table(
        "activity_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("resource", sa.String(length=32), nullable=False),
        sa.Column("resource_id", sa.BigInteger(), nullable=True),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("ip", sa.String(length=45), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"),
                  nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_activity_log_user_id"),
        sa.PrimaryKeyConstraint("id", name="pk_activity_log"),
    )
    op.create_index("ix_activity_log_created_at", "activity_log", ["created_at"])
    op.create_index("ix_activity_log_user_id_created_at", "activity_log", ["user_id", "created_at"])
    op.create_table(
        "login_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event", sa.String(length=24), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"),
                  nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_login_log_user_id"),
        sa.PrimaryKeyConstraint("id", name="pk_login_log"),
    )
    op.create_index("ix_login_log_created_at", "login_log", ["created_at"])
    op.create_index("ix_login_log_username_created_at", "login_log", ["username", "created_at"])

    conn = op.get_bind()
    perm = conn.execute(sa.text(
        "INSERT INTO permission (resource, action) VALUES ('logs', 'read_all')"
    )).lastrowid
    block = conn.execute(sa.text(
        "INSERT INTO access_group (name, is_system, owner_id) VALUES ('logs_viewer', 1, :o)"
    ), {"o": SYSTEM_USER_ID}).lastrowid
    conn.execute(sa.text(
        "INSERT INTO group_permission (group_id, permission_id) VALUES (:g, :p)"
    ), {"g": block, "p": perm})
    conn.execute(sa.text(
        "INSERT INTO group_closure (ancestor_id, descendant_id) VALUES (:g, :g)"
    ), {"g": block})
    for role in ROLES:
        role_id = conn.execute(sa.text(
            "SELECT id FROM access_group WHERE name = :n"
        ), {"n": role}).scalar_one()
        conn.execute(sa.text(
            "INSERT INTO group_group (parent_id, child_id) VALUES (:p, :c)"
        ), {"p": role_id, "c": block})
        conn.execute(sa.text(
            "INSERT INTO group_closure (ancestor_id, descendant_id) VALUES (:p, :c)"
        ), {"p": role_id, "c": block})


def downgrade() -> None:
    conn = op.get_bind()
    block = conn.execute(sa.text(
        "SELECT id FROM access_group WHERE name = 'logs_viewer'"
    )).scalar_one()
    for table, column in (("group_closure", "descendant_id"), ("group_group", "child_id")):
        conn.execute(sa.text(f"DELETE FROM {table} WHERE {column} = :g"), {"g": block})
    conn.execute(sa.text("DELETE FROM group_closure WHERE ancestor_id = :g"), {"g": block})
    conn.execute(sa.text("DELETE FROM group_permission WHERE group_id = :g"), {"g": block})
    conn.execute(sa.text("DELETE FROM user_group WHERE group_id = :g"), {"g": block})
    conn.execute(sa.text("DELETE FROM access_group WHERE id = :g"), {"g": block})
    conn.execute(sa.text("DELETE FROM permission WHERE resource = 'logs'"))
    op.drop_table("login_log")
    op.drop_table("activity_log")
