"""Group resolution and the escalation (subset) rule, against the real seed."""

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.authz import AuthUser, check_assignable_groups, effective_permissions
from tests.db.helpers import insert, make_group_with, make_login_user


@pytest.fixture
def session(conn):
    with Session(bind=conn) as s:
        yield s


def group_id(conn, name):
    from sqlalchemy import text

    return conn.execute(text("SELECT id FROM access_group WHERE name = :n"), {"n": name}).scalar_one()


def caller(session, user_id):
    return AuthUser(id=user_id, permissions=effective_permissions(session, user_id))


def test_user_without_groups_has_no_permissions(conn, session):
    assert effective_permissions(session, make_login_user(conn, "nobody")) == frozenset()


def test_role_resolves_through_nested_groups(conn, session):
    perms = effective_permissions(session, make_login_user(conn, "op", "operator"))
    assert ("contacts", "update") in perms and ("users", "read_all") in perms
    assert ("contacts", "delete") not in perms and ("messages", "delete") not in perms


def test_groups_are_additive(conn, session):
    uid = make_login_user(conn, "mix", "users_viewer", "messages_agent")
    assert effective_permissions(session, uid) == {
        ("users", "read_all"), ("messages", "create"), ("messages", "read_own"),
        ("messages", "read_received"),
    }


def test_soft_deleted_group_grants_nothing(conn, session):
    from tests.db.helpers import soft_delete

    uid = make_login_user(conn, "demoted", "auditor")
    soft_delete(conn, "access_group", group_id(conn, "auditor"))
    # the closure still lists the deleted group's own row, but it is excluded from resolution
    assert effective_permissions(session, uid) == frozenset()


def test_new_nesting_in_closure_is_honoured(conn, session):
    """A group that nests another via group_closure gains its permissions."""
    uid = make_login_user(conn, "nester")
    parent = make_group_with(conn, uid, "parent_grp", ("users", "read_all"))
    insert(conn, "group_closure", ancestor_id=parent, descendant_id=group_id(conn, "messages_viewer"))
    assert effective_permissions(session, uid) == {("users", "read_all"), ("messages", "read_all")}


@pytest.mark.parametrize(
    "holder, assignable, refused",
    [
        ("admin", ["admin", "operator", "agent", "auditor", "users_admin"], []),
        ("operator", ["agent", "contacts_viewer", "messages_viewer"], ["admin", "users_admin", "contacts_admin", "auditor", "logs_viewer"]),
        ("agent", ["contacts_viewer", "messages_agent"], ["operator", "auditor", "users_viewer", "admin"]),
    ],
)
def test_escalation_subset_rule(conn, session, holder, assignable, refused):
    me = caller(session, make_login_user(conn, f"holder_{holder}", holder))
    for name in assignable:
        check_assignable_groups(session, me, [group_id(conn, name)])  # no exception
    for name in refused:
        with pytest.raises(HTTPException) as exc:
            check_assignable_groups(session, me, [group_id(conn, name)])
        assert exc.value.status_code == 403, name


def test_one_unassignable_group_refuses_the_whole_set(conn, session):
    me = caller(session, make_login_user(conn, "op2", "operator"))
    with pytest.raises(HTTPException) as exc:
        check_assignable_groups(session, me, [group_id(conn, "agent"), group_id(conn, "admin")])
    assert exc.value.status_code == 403


def test_unknown_group_is_a_422_and_empty_is_fine(conn, session):
    me = caller(session, make_login_user(conn, "adm", "admin"))
    with pytest.raises(HTTPException) as exc:
        check_assignable_groups(session, me, [999999])
    assert exc.value.status_code == 422
    check_assignable_groups(session, me, [])


def test_escalation_uses_current_permissions_not_a_stale_snapshot(conn, session):
    uid = make_login_user(conn, "shrunk", "admin")
    stale = caller(session, uid)
    conn.exec_driver_sql("DELETE FROM user_group WHERE user_id = %s", (uid,))
    fresh = caller(session, uid)
    check_assignable_groups(session, stale, [group_id(conn, "admin")])  # stale would pass
    with pytest.raises(HTTPException):
        check_assignable_groups(session, fresh, [group_id(conn, "agent")])

