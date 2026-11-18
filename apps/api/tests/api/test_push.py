"""Push notifications for staff: /auth/me/push and the push sent when an SMS is received."""

import itertools
import json

import pytest
from sqlalchemy import text

from app import push
from app.config import settings
from tests.api.conftest import auth_header
from tests.api.worker_helpers import make_worker_with_device
from tests.db.helpers import make_contact, make_group_with, make_login_user, make_message

pytestmark = pytest.mark.db

SMS = {
    "ref": "r1",
    "sender": "0917 123 4567",
    "content": "my secret text",
    "received_at": "2026-11-09T08:00:00Z",
}


def keys(n=1):
    return {"p256dh": f"key{n}", "auth": f"auth{n}"}


def subscription(n=1):
    return {"endpoint": f"https://push.example.com/send/{n}", "keys": keys(n)}


@pytest.fixture(autouse=True)
def vapid(monkeypatch):
    public, _ = push.new_vapid_keys()
    monkeypatch.setattr(settings, "vapid_public_key", public)
    return public


def subscribe(client, headers, n=1):
    r = client.put("/auth/me/push", json=subscription(n), headers=headers)
    assert r.status_code == 204, r.text


def rows(db):
    return db.execute(
        text("SELECT user_id, endpoint, p256dh, auth FROM push_subscription ORDER BY id")
    ).all()


# --- configuration and subscribing ---------------------------------------------------------


def test_the_settings_endpoint_gives_the_public_key(client, conn, vapid):
    make_login_user(conn, "alice", "agent")
    r = client.get("/auth/me/push", headers=auth_header(client, "alice"))
    assert r.status_code == 200 and r.json() == {"enabled": True, "public_key": vapid}


def test_push_reports_itself_off_without_keys(client, conn, monkeypatch):
    monkeypatch.setattr(settings, "vapid_public_key", "")
    make_login_user(conn, "alice", "agent")
    h = auth_header(client, "alice")
    assert client.get("/auth/me/push", headers=h).json() == {"enabled": False, "public_key": None}
    assert client.put("/auth/me/push", json=subscription(), headers=h).status_code == 409


@pytest.mark.parametrize("call", ["get", "put", "delete"])
def test_every_push_endpoint_needs_a_sign_in(client, call):
    r = client.request(call.upper(), "/auth/me/push", json=None if call == "get" else subscription())
    assert r.status_code == 401


def test_subscribing_stores_the_subscription_for_the_caller(client, conn, db):
    alice = make_login_user(conn, "alice", "agent")
    subscribe(client, auth_header(client, "alice"))
    assert rows(db) == [(alice, "https://push.example.com/send/1", "key1", "auth1")]


def test_subscribing_again_from_the_same_browser_keeps_one_row_with_the_new_keys(client, conn, db):
    make_login_user(conn, "alice", "agent")
    h = auth_header(client, "alice")
    subscribe(client, h)
    r = client.put(
        "/auth/me/push", json={**subscription(), "keys": {"p256dh": "new", "auth": "newer"}}, headers=h
    )
    assert r.status_code == 204
    [row] = rows(db)
    assert (row.p256dh, row.auth) == ("new", "newer")


def test_one_person_can_have_several_browsers(client, conn, db):
    make_login_user(conn, "alice", "agent")
    h = auth_header(client, "alice")
    subscribe(client, h, 1)
    subscribe(client, h, 2)
    assert len(rows(db)) == 2


def test_the_same_browser_signing_in_as_someone_else_moves_the_subscription(client, conn, db):
    alice = make_login_user(conn, "alice", "agent")
    bob = make_login_user(conn, "bob", "agent")
    subscribe(client, auth_header(client, "alice"))
    subscribe(client, auth_header(client, "bob"))
    [row] = rows(db)
    assert row.user_id == bob != alice


@pytest.mark.parametrize(
    "body",
    [
        {"endpoint": "http://push.example.com/1", "keys": keys()},  # not https
        {"endpoint": "not a url", "keys": keys()},
        {"endpoint": "https://push.example.com/1"},  # no keys
        {"endpoint": "https://push.example.com/1", "keys": {"p256dh": "", "auth": "a"}},
        {"endpoint": "https://push.example.com/1", "keys": {"p256dh": "k"}},
    ],
)
def test_a_bad_subscription_is_refused(client, conn, db, body):
    make_login_user(conn, "alice", "agent")
    r = client.put("/auth/me/push", json=body, headers=auth_header(client, "alice"))
    assert r.status_code == 422 and rows(db) == []


def test_unsubscribing_removes_only_the_callers_own_subscription(client, conn, db):
    make_login_user(conn, "alice", "agent")
    make_login_user(conn, "bob", "agent")
    ha, hb = auth_header(client, "alice"), auth_header(client, "bob")
    subscribe(client, ha, 1)
    subscribe(client, hb, 2)
    # bob cannot remove alice's, and is not told whether it exists
    assert client.request("DELETE", "/auth/me/push", json={"endpoint": subscription(1)["endpoint"]}, headers=hb).status_code == 204
    assert len(rows(db)) == 2
    assert client.request("DELETE", "/auth/me/push", json={"endpoint": subscription(1)["endpoint"]}, headers=ha).status_code == 204
    assert [r.endpoint for r in rows(db)] == [subscription(2)["endpoint"]]


def test_unsubscribing_from_an_unknown_endpoint_is_a_no_op(client, conn):
    make_login_user(conn, "alice", "agent")
    r = client.request("DELETE", "/auth/me/push", json={"endpoint": "https://x.example.com/1"}, headers=auth_header(client, "alice"))
    assert r.status_code == 204


def test_subscribing_and_unsubscribing_are_logged_without_the_endpoint(client, conn, db):
    make_login_user(conn, "alice", "agent")
    h = auth_header(client, "alice")
    subscribe(client, h)
    client.request("DELETE", "/auth/me/push", json={"endpoint": subscription()["endpoint"]}, headers=h)
    entries = db.execute(
        text("SELECT action, resource, summary FROM activity_log WHERE resource = 'push' ORDER BY id")
    ).all()
    assert [e.action for e in entries] == ["subscribe", "unsubscribe"]
    assert all("push.example.com" not in e.summary for e in entries)


# --- what is queued when an SMS arrives -----------------------------------------------------


@pytest.fixture
def worker(client, db):
    headers, device = make_worker_with_device(client, db)
    db.commit()
    return headers, device


def receive(client, worker, **over):
    headers, device = worker
    return client.post("/worker/inbound", json={"device_id": device.id, **SMS, **over}, headers=headers)


_ids = itertools.count(100)


def staff(client, conn, username, *groups):
    """Someone with one subscribed browser; returns its endpoint."""
    make_login_user(conn, username, *groups)
    n = next(_ids)
    subscribe(client, auth_header(client, username), n)
    return f"https://push.example.com/send/{n}"


def queued(conn):
    """The outbox as {endpoint: (count, senders, last_message_id, state)}."""
    rows = conn.execute(
        text(
            "SELECT s.endpoint, o.message_count, o.senders, o.last_message_id, o.state "
            "FROM push_outbox o JOIN push_subscription s ON s.id = o.subscription_id"
        )
    ).all()
    return {r.endpoint: (r.message_count, json.loads(r.senders), r.last_message_id, r.state) for r in rows}


def test_people_who_can_see_received_messages_are_queued(client, conn, worker):
    agent = staff(client, conn, "agent1", "agent")  # read_received
    admin = staff(client, conn, "admin1", "admin")  # read_all
    auditor = staff(client, conn, "auditor1", "auditor")  # read_all
    assert receive(client, worker).status_code == 200
    assert set(queued(conn)) == {agent, admin, auditor}


def test_the_queue_holds_who_it_is_from_and_never_the_text(client, conn, worker):
    endpoint = staff(client, conn, "agent1", "agent")
    receive(client, worker)
    message_id = conn.execute(text("SELECT id FROM messages")).scalar_one()
    assert queued(conn) == {endpoint: (1, ["+639171234567"], message_id, "pending")}
    dump = conn.execute(text("SELECT * FROM push_outbox")).all()
    assert "secret" not in str(dump)


def test_a_known_contact_is_named(client, conn, worker):
    from tests.db.helpers import make_phone

    cid = make_contact(conn, "Maria Santos")
    make_phone(conn, cid, "+639171234567")
    endpoint = staff(client, conn, "agent1", "agent")
    receive(client, worker)
    assert queued(conn)[endpoint][1] == ["Maria Santos"]


def test_the_first_attempt_waits_for_the_aggregation_window(client, conn, worker, monkeypatch):
    monkeypatch.setattr(settings, "push_aggregate_seconds", 5)
    staff(client, conn, "agent1", "agent")
    receive(client, worker)
    wait = conn.execute(
        text("SELECT TIMESTAMPDIFF(SECOND, UTC_TIMESTAMP(), send_after) FROM push_outbox")
    ).scalar_one()
    assert 3 <= wait <= 6


def test_a_second_message_joins_the_waiting_notification(client, conn, worker):
    endpoint = staff(client, conn, "agent1", "agent")
    receive(client, worker)
    first = conn.execute(text("SELECT send_after FROM push_outbox")).scalar_one()
    receive(client, worker, ref="r2", sender="0918 000 0000")
    receive(client, worker, ref="r3")  # the first sender again
    last = conn.execute(text("SELECT MAX(id) FROM messages")).scalar_one()
    assert queued(conn) == {endpoint: (3, ["+639171234567", "+639180000000"], last, "pending")}
    # joining does not push the send time back, or a busy phone line would never notify anyone
    assert conn.execute(text("SELECT send_after FROM push_outbox")).scalar_one() == first


def test_each_browser_has_its_own_row(client, conn, worker):
    make_login_user(conn, "agent1", "agent")
    h = auth_header(client, "agent1")
    subscribe(client, h, 1)
    subscribe(client, h, 2)
    receive(client, worker)
    assert set(queued(conn)) == {subscription(1)["endpoint"], subscription(2)["endpoint"]}


def test_people_who_cannot_see_received_messages_are_not_queued(client, conn, worker):
    own_only = make_login_user(conn, "ownonly")
    make_group_with(conn, own_only, "own_only", ("messages", "read_own"))
    subscribe(client, auth_header(client, "ownonly"), 1)
    make_login_user(conn, "nobody", "contacts_viewer")  # no message permission at all
    subscribe(client, auth_header(client, "nobody"), 2)
    receive(client, worker)
    assert queued(conn) == {}


def test_permissions_are_read_when_queueing(client, conn, worker):
    agent = make_login_user(conn, "agent1", "agent")
    subscribe(client, auth_header(client, "agent1"), 1)
    conn.execute(text("DELETE FROM user_group WHERE user_id = :u"), {"u": agent})
    receive(client, worker)
    assert queued(conn) == {}


def test_a_deleted_or_disabled_user_is_not_queued(client, conn, worker):
    gone = make_login_user(conn, "gone", "agent")
    subscribe(client, auth_header(client, "gone"), 1)
    off = make_login_user(conn, "off", "agent")
    subscribe(client, auth_header(client, "off"), 2)
    conn.execute(text("UPDATE users SET deleted_at = NOW() WHERE id = :u"), {"u": gone})
    conn.execute(text("UPDATE users SET login_enabled = 0 WHERE id = :u"), {"u": off})
    receive(client, worker)
    assert queued(conn) == {}


def test_a_repeated_delivery_does_not_queue_again(client, conn, worker):
    endpoint = staff(client, conn, "agent1", "agent")
    receive(client, worker)
    receive(client, worker)  # same ref
    assert queued(conn)[endpoint][0] == 1


def test_a_sender_that_is_not_a_number_queues_nothing(client, conn, worker):
    staff(client, conn, "agent1", "agent")
    receive(client, worker, sender="PROMO", ref="r2")
    assert queued(conn) == {}


def test_nothing_is_queued_when_push_is_not_configured(client, conn, worker, monkeypatch):
    staff(client, conn, "agent1", "agent")
    monkeypatch.setattr(settings, "vapid_public_key", "")
    receive(client, worker)
    assert queued(conn) == {}


def test_the_android_webhook_queues_too(client, conn, db):
    from app.devices import register_device
    from tests.api.test_device_webhook import post, received

    device = register_device(db, "phone1", "+639170000000")
    db.commit()
    staff(client, conn, "agent1", "agent")
    assert post(client, device.id, received()).status_code == 200
    assert len(queued(conn)) == 1


def test_a_delivery_failure_queues_nothing(client, conn, db):
    """Only a stored inbound SMS triggers a push."""
    from app.devices import register_device
    from tests.api.test_device_webhook import post

    device = register_device(db, "phone1", "+639170000000")
    db.commit()
    sender = make_login_user(conn, "sender", "agent")
    mid = make_message(
        conn, make_contact(conn, "Bob"), owner_id=sender, status="sending", gsm_device_id=device.id
    )
    staff(client, conn, "agent1", "agent")
    payload = {
        "deviceId": "d", "event": "sms:failed", "id": "evt-9", "webhookId": "wh",
        "payload": {"messageId": f"cc-{mid}", "reason": "no credit", "failedAt": "2026-11-09T08:00:00Z"},
    }  # fmt: skip
    assert post(client, device.id, payload).status_code == 200
    assert queued(conn) == {}


def test_a_failure_to_queue_never_loses_the_sms(client, conn, worker, monkeypatch):
    from app import push_outbox

    staff(client, conn, "agent1", "agent")

    def boom(*a, **k):
        raise RuntimeError("outbox is broken")

    monkeypatch.setattr(push_outbox, "enqueue_inbound", boom)
    r = receive(client, worker)
    assert r.status_code == 200 and r.json()["stored"] is True
    assert conn.execute(text("SELECT COUNT(*) FROM messages")).scalar_one() == 1
    assert queued(conn) == {}
