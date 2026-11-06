import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.db.helpers import insert, make_user, soft_delete


def _group(conn, name):
    return insert(conn, "access_group", name=name, is_system=0, owner_id=1)


def test_permission_resource_action_pairs_are_unique(conn):
    insert(conn, "permission", resource="widgets", action="create")
    with pytest.raises(DBAPIError, match="uq_permission_resource_action"):
        insert(conn, "permission", resource="widgets", action="create")


def test_group_name_is_unique_among_active_groups_and_reusable_after_delete(conn):
    first = _group(conn, "ops")
    with pytest.raises(DBAPIError, match="uq_access_group_active_name"):
        _group(conn, "ops")
    soft_delete(conn, "access_group", first)
    _group(conn, "ops")


def test_a_group_cannot_contain_itself(conn):
    g = _group(conn, "loop")
    with pytest.raises(DBAPIError, match="ck_group_group_no_self_nesting"):
        conn.execute(text("INSERT INTO group_group (parent_id, child_id) VALUES (:a, :a)"), {"a": g})


def test_group_membership_rows_are_unique(conn):
    g, u = _group(conn, "g1"), make_user(conn, "m1")
    conn.execute(text("INSERT INTO user_group (user_id, group_id) VALUES (:u, :g)"), {"u": u, "g": g})
    with pytest.raises(DBAPIError, match="Duplicate entry"):
        conn.execute(
            text("INSERT INTO user_group (user_id, group_id) VALUES (:u, :g)"), {"u": u, "g": g}
        )


def test_group_permission_requires_existing_rows(conn):
    g = _group(conn, "g2")
    with pytest.raises(DBAPIError, match="fk_group_permission_permission_id"):
        conn.execute(
            text("INSERT INTO group_permission (group_id, permission_id) VALUES (:g, 999999)"),
            {"g": g},
        )
