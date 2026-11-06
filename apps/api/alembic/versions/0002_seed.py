"""Seed system agents, permissions and the default groups.

No human user is seeded here: the first admin is created by a bootstrap command (Phase 2) so that
no default credential ever ships in a migration. GSM device agents are created when a device is
registered (Phase 5).

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

SYSTEM_USER_ID = 1

PERMISSIONS = (
    [(r, a) for r in ("users", "contacts") for a in ("create", "read_all", "read_own", "update", "delete")]
    + [("messages", a) for a in ("create", "read_all", "read_own", "read_received", "delete")]
    + [("groups", "read_all")]
)

# Building-block groups: name -> permissions.
BLOCKS = {
    "users_admin": [("users", "create"), ("users", "read_all"), ("users", "update"),
                    ("users", "delete"), ("groups", "read_all")],
    "users_viewer": [("users", "read_all")],
    "contacts_admin": [("contacts", "create"), ("contacts", "read_all"), ("contacts", "update"),
                       ("contacts", "delete")],
    "contacts_editor": [("contacts", "create"), ("contacts", "read_all"), ("contacts", "update")],
    "contacts_viewer": [("contacts", "read_all")],
    "messages_admin": [("messages", "create"), ("messages", "read_all"), ("messages", "delete")],
    "messages_operator": [("messages", "create"), ("messages", "read_all")],
    "messages_agent": [("messages", "create"), ("messages", "read_own"),
                       ("messages", "read_received")],
    "messages_viewer": [("messages", "read_all")],
}

# Roles: name -> child groups.
ROLES = {
    "admin": ["users_admin", "contacts_admin", "messages_admin"],
    "operator": ["contacts_editor", "messages_operator", "users_viewer"],
    "agent": ["contacts_viewer", "messages_agent"],
    "auditor": ["contacts_viewer", "messages_viewer", "users_viewer"],
}


def _closure(nesting: dict[str, list[str]], names: list[str]) -> set[tuple[str, str]]:
    """Reflexive, transitive (ancestor, descendant) pairs."""
    pairs = {(n, n) for n in names}
    changed = True
    while changed:
        changed = False
        for parent, children in nesting.items():
            for child in children:
                new = {(parent, child)} | {(parent, d) for (a, d) in pairs if a == child}
                if not new <= pairs:
                    pairs |= new
                    changed = True
    return pairs


def upgrade() -> None:
    conn = op.get_bind()

    # The system user and its contact own each other, so insert both with explicit ids while
    # foreign keys are not checked. Every later row is inserted normally.
    conn.execute(sa.text("SET FOREIGN_KEY_CHECKS = 0"))
    conn.execute(sa.text(
        "INSERT INTO contacts (id, name, type, owner_id) VALUES (1, 'System', 'entity', :o)"
    ), {"o": SYSTEM_USER_ID})
    conn.execute(sa.text(
        "INSERT INTO users (id, contact_id, username, is_system, agent_direction, login_enabled,"
        " owner_id) VALUES (:o, 1, 'system', 1, 'outbound', 0, :o)"
    ), {"o": SYSTEM_USER_ID})
    conn.execute(sa.text("SET FOREIGN_KEY_CHECKS = 1"))

    contact_id = conn.execute(sa.text(
        "INSERT INTO contacts (name, type, owner_id) VALUES ('Notification', 'entity', :o)"
    ), {"o": SYSTEM_USER_ID}).lastrowid
    conn.execute(sa.text(
        "INSERT INTO users (contact_id, username, is_system, agent_direction, login_enabled,"
        " owner_id) VALUES (:c, 'notification', 1, 'outbound', 0, :o)"
    ), {"c": contact_id, "o": SYSTEM_USER_ID})

    perm_id = {}
    for resource, action in PERMISSIONS:
        perm_id[(resource, action)] = conn.execute(sa.text(
            "INSERT INTO permission (resource, action) VALUES (:r, :a)"
        ), {"r": resource, "a": action}).lastrowid

    group_id = {}
    for name in [*BLOCKS, *ROLES]:
        group_id[name] = conn.execute(sa.text(
            "INSERT INTO access_group (name, is_system, owner_id) VALUES (:n, 1, :o)"
        ), {"n": name, "o": SYSTEM_USER_ID}).lastrowid

    for name, perms in BLOCKS.items():
        for perm in perms:
            conn.execute(sa.text(
                "INSERT INTO group_permission (group_id, permission_id) VALUES (:g, :p)"
            ), {"g": group_id[name], "p": perm_id[perm]})

    for parent, children in ROLES.items():
        for child in children:
            conn.execute(sa.text(
                "INSERT INTO group_group (parent_id, child_id) VALUES (:p, :c)"
            ), {"p": group_id[parent], "c": group_id[child]})

    for ancestor, descendant in sorted(_closure(ROLES, list(group_id))):
        conn.execute(sa.text(
            "INSERT INTO group_closure (ancestor_id, descendant_id) VALUES (:a, :d)"
        ), {"a": group_id[ancestor], "d": group_id[descendant]})


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("SET FOREIGN_KEY_CHECKS = 0"))
    for table in ("group_closure", "group_group", "group_permission", "user_group",
                  "access_group", "permission", "users", "contacts"):
        conn.execute(sa.text(f"DELETE FROM {table}"))
    conn.execute(sa.text("SET FOREIGN_KEY_CHECKS = 1"))
