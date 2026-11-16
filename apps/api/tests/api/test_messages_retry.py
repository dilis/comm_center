import pytest
from sqlalchemy import text

from tests.api.conftest import auth_header
from tests.db.helpers import (
    make_contact,
    make_inbound_agent,
    make_login_user,
    make_message,
    make_phone,
    soft_delete,
)

pytestmark = pytest.mark.db


@pytest.fixture
def boss(conn):
    return make_login_user(conn, "boss", "admin")


@pytest.fixture
def h(client, boss):
    return auth_header(client, "boss")


@pytest.fixture
def ana(conn):
    cid = make_contact(conn, first_name="Ana", last_name="Cruz")
    make_phone(conn, cid, "+639171234567", is_primary=1)
    return cid


@pytest.fixture
def failed(conn, boss, ana):
    return make_message(
        conn, ana, owner_id=boss, status="failed", error_message="the phone answered HTTP 500",
        sent_at=None,
    )


def retry(client, h, message_id):
    return client.post(f"/messages/{message_id}/retry", headers=h)


def row(conn, message_id):
    return conn.execute(
        text("SELECT status, error_message, send_attempt FROM messages WHERE id=:i"),
        {"i": message_id},
    ).one()


def test_retry_queues_a_failed_message_again_and_clears_the_error(client, conn, h, failed):
    r = retry(client, h, failed)
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["error_message"]) == ("queued", None)
    assert tuple(row(conn, failed)) == ("queued", None, 1)


def test_every_retry_counts_one_more_attempt(client, conn, h, failed):
    retry(client, h, failed)
    conn.execute(text("UPDATE messages SET status='failed' WHERE id=:i"), {"i": failed})
    assert retry(client, h, failed).status_code == 200
    assert row(conn, failed).send_attempt == 2


@pytest.mark.parametrize("status", ["queued", "sending", "sent", "delivered"])
def test_only_a_failed_message_can_be_retried(client, conn, h, boss, ana, status):
    mid = make_message(conn, ana, owner_id=boss, status=status)
    r = retry(client, h, mid)
    assert r.status_code == 409, r.text
    assert tuple(row(conn, mid))[::2] == (status, 0)


def test_a_received_message_cannot_be_retried(client, conn, h, ana):
    mid = make_message(conn, ana, owner_id=make_inbound_agent(conn), status="received")
    assert retry(client, h, mid).status_code == 422


def test_retrying_twice_at_once_queues_it_only_once(client, conn, h, failed):
    assert retry(client, h, failed).status_code == 200
    assert retry(client, h, failed).status_code == 409  # now queued
    assert row(conn, failed).send_attempt == 1


def test_a_missing_or_deleted_message_is_404(client, conn, h, failed):
    assert retry(client, h, 99999).status_code == 404
    soft_delete(conn, "messages", failed)
    assert retry(client, h, failed).status_code == 404


def test_an_agent_cannot_retry_a_message_it_cannot_see(client, conn, boss, ana, failed):
    make_login_user(conn, "viewer", "agent")  # agents read only their own and received messages
    r = retry(client, auth_header(client, "viewer"), failed)
    assert r.status_code == 404
    assert row(conn, failed).status == "failed"


def test_retry_is_written_to_the_activity_log(client, conn, h, boss, failed):
    retry(client, h, failed)
    summary = conn.execute(
        text("SELECT action, resource, resource_id, summary FROM activity_log ORDER BY id DESC LIMIT 1")
    ).one()
    assert (summary.action, summary.resource, summary.resource_id) == ("retry", "message", failed)
    assert "hello" not in summary.summary  # never the message text
