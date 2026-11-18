import pytest
from sqlalchemy.exc import DBAPIError

from tests.db.helpers import insert, make_login_user

pytestmark = pytest.mark.db


def sub(conn, user_id, endpoint="https://p/1", endpoint_hash="a" * 64):
    return insert(
        conn, "push_subscription", user_id=user_id, endpoint=endpoint,
        endpoint_hash=endpoint_hash, p256dh="k", auth="a",
    )  # fmt: skip


def test_an_endpoint_is_held_once(conn):
    u = make_login_user(conn, "alice", "agent")
    sub(conn, u)
    with pytest.raises(DBAPIError, match="uq_push_subscription_endpoint_hash"):
        sub(conn, u)


def test_a_subscription_needs_an_existing_user(conn):
    with pytest.raises(DBAPIError, match="fk_push_subscription_user_id"):
        sub(conn, 999999)


def test_endpoints_longer_than_an_index_allows_are_stored(conn):
    u = make_login_user(conn, "alice", "agent")
    long = "https://push.example.com/" + "x" * 1500
    sub(conn, u, endpoint=long, endpoint_hash="b" * 64)
