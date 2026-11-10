import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.db.helpers import make_contact, make_user, soft_delete


def test_username_is_unique_among_active_users(conn):
    make_user(conn, "jane")
    with pytest.raises(DBAPIError, match="uq_users_active_username"):
        make_user(conn, "jane")


def test_username_is_reusable_after_soft_delete(conn):
    first = make_user(conn, "jane")
    soft_delete(conn, "users", first)
    make_user(conn, "jane")


def test_a_contact_can_be_linked_to_only_one_user(conn):
    contact = make_contact(conn, "Jane")
    make_user(conn, "jane", contact_id=contact)
    with pytest.raises(DBAPIError, match="uq_users_contact_id"):
        make_user(conn, "jane2", contact_id=contact)


def test_user_requires_an_existing_contact_and_owner(conn):
    with pytest.raises(DBAPIError, match="fk_users_contact_id"):
        make_user(conn, "ghost", contact_id=999999)
    with pytest.raises(DBAPIError, match="fk_users_owner_id"):
        make_user(conn, "orphan", contact_id=make_contact(conn, "Orphan"), owner_id=999999)


def test_system_agent_requires_a_direction(conn):
    with pytest.raises(DBAPIError, match="ck_users_agent_direction_iff_system"):
        make_user(conn, "agent", is_system=1, login_enabled=0)


def test_human_cannot_have_a_direction(conn):
    with pytest.raises(DBAPIError, match="ck_users_agent_direction_iff_system"):
        make_user(conn, "human", agent_direction="inbound")


def test_system_agent_cannot_log_in(conn):
    with pytest.raises(DBAPIError, match="ck_users_system_agent_cannot_log_in"):
        make_user(conn, "a1", is_system=1, agent_direction="inbound", login_enabled=1)


def test_system_agent_may_hold_a_secret_for_its_worker(conn):
    """A worker signs in as its device's agent: the hash is its secret, not a web password."""
    make_user(
        conn, "a2", is_system=1, agent_direction="inbound", login_enabled=0, password_hash="x"
    )


def test_system_agent_cannot_be_soft_deleted(conn):
    agent = make_user(conn, "a3", is_system=1, agent_direction="inbound", login_enabled=0)
    with pytest.raises(DBAPIError, match="ck_users_system_agent_not_deletable"):
        soft_delete(conn, "users", agent)


def test_is_system_and_agent_direction_are_immutable(conn):
    agent = make_user(conn, "a4", is_system=1, agent_direction="inbound", login_enabled=0)
    human = make_user(conn, "h1")
    with pytest.raises(DBAPIError, match="immutable"):
        conn.execute(text("UPDATE users SET agent_direction='outbound' WHERE id=:i"), {"i": agent})
    with pytest.raises(DBAPIError, match="immutable"):
        conn.execute(text("UPDATE users SET is_system=1 WHERE id=:i"), {"i": human})


def test_contact_type_must_be_person_or_entity(conn):
    with pytest.raises(DBAPIError, match="Data truncated"):
        make_contact(conn, "Weird", type="alien")
