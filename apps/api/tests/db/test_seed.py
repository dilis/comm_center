import pytest
from sqlalchemy import text

# The permission matrix the seed must produce (from SPECS.md section 4.6).
USERS_ADMIN = {("users", a) for a in ("create", "read_all", "update", "delete")} | {
    ("groups", "read_all")
}
CONTACTS_ADMIN = {("contacts", a) for a in ("create", "read_all", "update", "delete")}
MESSAGES_ADMIN = {("messages", a) for a in ("create", "read_all", "delete")}

EXPECTED_GROUPS = {
    "users_admin": USERS_ADMIN,
    "users_viewer": {("users", "read_all")},
    "contacts_admin": CONTACTS_ADMIN,
    "contacts_editor": {("contacts", a) for a in ("create", "read_all", "update")},
    "contacts_viewer": {("contacts", "read_all")},
    "messages_admin": MESSAGES_ADMIN,
    "messages_operator": {("messages", "create"), ("messages", "read_all")},
    "messages_agent": {("messages", a) for a in ("create", "read_own", "read_received")},
    "messages_viewer": {("messages", "read_all")},
    "admin": USERS_ADMIN | CONTACTS_ADMIN | MESSAGES_ADMIN,
    "operator": (
        {("contacts", a) for a in ("create", "read_all", "update")}
        | {("messages", "create"), ("messages", "read_all")}
        | {("users", "read_all")}
    ),
    "agent": {("contacts", "read_all")}
    | {("messages", a) for a in ("create", "read_own", "read_received")},
    "auditor": {("contacts", "read_all"), ("messages", "read_all"), ("users", "read_all")},
}


def effective(conn, group_name):
    rows = conn.execute(
        text(
            """
            SELECT p.resource, p.action
            FROM access_group g
            JOIN group_closure c ON c.ancestor_id = g.id
            JOIN group_permission gp ON gp.group_id = c.descendant_id
            JOIN permission p ON p.id = gp.permission_id
            WHERE g.name = :n AND g.deleted_at IS NULL
            """
        ),
        {"n": group_name},
    )
    return {(r.resource, r.action) for r in rows}


def test_system_agent_is_seeded_first_and_owns_itself(conn):
    row = conn.execute(text("SELECT * FROM users WHERE id = 1")).one()
    assert row.username == "system"
    assert row.owner_id == 1
    assert row.is_system and row.agent_direction == "outbound"
    assert not row.login_enabled and row.password_hash is None
    contact = conn.execute(text("SELECT * FROM contacts WHERE id = :c"), {"c": row.contact_id}).one()
    assert contact.id == 1 and contact.owner_id == 1 and contact.name == "System"


def test_notification_agent_is_an_outbound_system_agent(conn):
    row = conn.execute(text("SELECT * FROM users WHERE username = 'notification'")).one()
    assert row.is_system and row.agent_direction == "outbound" and not row.login_enabled
    assert row.owner_id == 1


def test_no_human_users_are_seeded(conn):
    assert conn.execute(text("SELECT COUNT(*) FROM users WHERE is_system = 0")).scalar() == 0


def test_every_seeded_user_has_a_distinct_contact(conn):
    rows = conn.execute(text("SELECT COUNT(DISTINCT contact_id), COUNT(*) FROM users")).one()
    assert rows[0] == rows[1]


def test_permission_catalogue(conn):
    got = {(r.resource, r.action) for r in conn.execute(text("SELECT resource, action FROM permission"))}
    expected = (
        {(r, a) for r in ("users", "contacts") for a in ("create", "read_all", "read_own", "update", "delete")}
        | {("messages", a) for a in ("create", "read_all", "read_own", "read_received", "delete")}
        | {("groups", "read_all")}
    )
    assert got == expected
    assert ("messages", "update") not in got  # messages are an immutable log


def test_seeded_groups_are_system_groups_owned_by_system(conn):
    rows = conn.execute(text("SELECT name, is_system, owner_id FROM access_group")).all()
    assert {r.name for r in rows} == set(EXPECTED_GROUPS)
    assert all(r.is_system and r.owner_id == 1 for r in rows)


@pytest.mark.parametrize("group", sorted(EXPECTED_GROUPS))
def test_effective_permissions_of_each_seeded_group(conn, group):
    assert effective(conn, group) == EXPECTED_GROUPS[group]


def test_closure_is_reflexive_and_includes_nested_groups(conn):
    pairs = {
        (r.a, r.d)
        for r in conn.execute(
            text(
                """SELECT a.name a, d.name d FROM group_closure c
                   JOIN access_group a ON a.id = c.ancestor_id
                   JOIN access_group d ON d.id = c.descendant_id"""
            )
        )
    }
    assert ("admin", "admin") in pairs and ("users_viewer", "users_viewer") in pairs
    assert ("admin", "users_admin") in pairs and ("operator", "users_viewer") in pairs
    assert ("agent", "admin") not in pairs


def test_no_seeded_agent_group_can_reach_admin_permissions(conn):
    assert ("users", "delete") not in effective(conn, "agent")
    assert ("messages", "delete") not in effective(conn, "operator")
