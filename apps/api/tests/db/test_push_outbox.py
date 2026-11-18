import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.db.helpers import insert, make_login_user

pytestmark = pytest.mark.db


def subscription(conn, user_id, n=1):
    return insert(
        conn, "push_subscription", user_id=user_id, endpoint=f"https://p/{n}",
        endpoint_hash=f"{n:064d}", p256dh="k", auth="a",
    )  # fmt: skip


def outbox(conn, sub_id, state="pending", **cols):
    cols.setdefault("send_after", "2026-11-09 08:00:00")
    return insert(
        conn, "push_outbox", subscription_id=sub_id, state=state, message_count=1,
        last_message_id=None, senders="[]", attempts=0, **cols,
    )  # fmt: skip


def test_a_subscription_has_one_pending_row(conn):
    sub = subscription(conn, make_login_user(conn, "alice", "agent"))
    outbox(conn, sub)
    with pytest.raises(DBAPIError, match="uq_push_outbox_pending_key"):
        outbox(conn, sub)


def test_rows_being_sent_do_not_count_as_pending(conn):
    sub = subscription(conn, make_login_user(conn, "alice", "agent"))
    outbox(conn, sub, "sending", lease_until="2026-11-09 08:01:00")
    outbox(conn, sub, "sending", lease_until="2026-11-09 08:01:00")
    outbox(conn, sub)  # and one pending beside them
    outbox(conn, subscription(conn, make_login_user(conn, "bob", "agent"), 2))  # others are free


def test_a_state_other_than_pending_or_sending_is_refused(conn):
    sub = subscription(conn, make_login_user(conn, "alice", "agent"))
    with pytest.raises(DBAPIError, match="ck_push_outbox_state"):
        outbox(conn, sub, "done")


def test_deleting_a_subscription_takes_its_outbox_rows_with_it(conn):
    sub = subscription(conn, make_login_user(conn, "alice", "agent"))
    outbox(conn, sub)
    conn.execute(text("DELETE FROM push_subscription WHERE id = :i"), {"i": sub})
    assert conn.execute(text("SELECT COUNT(*) FROM push_outbox")).scalar_one() == 0


def test_a_row_needs_an_existing_subscription(conn):
    with pytest.raises(DBAPIError, match="fk_push_outbox_subscription_id"):
        outbox(conn, 999999)
