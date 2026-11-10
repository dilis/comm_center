"""POST /worker/claim: hand the next queued message to a worker, under a lease."""

import pytest
from sqlalchemy import text

import app.routers.worker as worker_router
from app.config import settings
from app.devices import register_device
from tests.api.conftest import auth_header
from tests.api.test_worker_auth import SESSION
from tests.api.worker_helpers import (
    PHONE,
    lease_row,
    make_worker_with_device,
    message_row,
    other_worker,
)
from tests.db.helpers import make_contact, make_login_user, make_message, make_phone

pytestmark = pytest.mark.db


@pytest.fixture
def setup(client, db):
    headers, device = make_worker_with_device(client, db)
    db.commit()
    return headers, device


@pytest.fixture
def ana(conn):
    cid = make_contact(conn, "Ana")
    make_phone(conn, cid, PHONE, is_primary=1)
    return cid


def claim(client, headers, device, **body):
    return client.post("/worker/claim", json={"device_id": device.id, **body}, headers=headers)


def test_an_empty_queue_gives_no_message(client, setup):
    headers, device = setup
    r = claim(client, headers, device)
    assert r.status_code == 200 and r.json()["message"] is None


def test_the_oldest_queued_message_is_claimed_and_leased(client, conn, db, setup, ana):
    headers, device = setup
    first = make_message(conn, ana, content="first")
    second = make_message(conn, ana, content="second")
    r = claim(client, headers, device)
    body = r.json()
    assert body["message"] == {"id": first, "phone_number": PHONE, "content": "first"}
    assert body["lease_seconds"] == settings.worker_lease_seconds
    row = message_row(db, first)
    assert (row.status, row.gsm_device_id) == ("sending", device.id)
    assert message_row(db, second).status == "queued"
    lease = lease_row(db, first)
    assert lease.device_id == device.id and lease.expires_at is not None


def test_a_claimed_message_is_not_handed_out_twice(client, conn, setup, ana):
    headers, device = setup
    make_message(conn, ana)
    assert claim(client, headers, device).json()["message"] is not None
    assert claim(client, headers, device).json()["message"] is None


def test_a_message_meant_for_one_device_is_not_given_to_another(client, conn, db, setup, ana):
    headers, device = setup
    other_headers, other = other_worker(client, db)
    meant_for_other = make_message(conn, ana, content="for d2", gsm_device_id=other.id)
    assert claim(client, headers, device).json()["message"] is None
    assert message_row(db, meant_for_other).status == "queued"
    got = claim(client, other_headers, other).json()["message"]
    assert got["id"] == meant_for_other


def test_a_device_skips_what_is_meant_for_others_to_reach_what_anyone_may_take(
    client, conn, db, setup, ana
):
    headers, device = setup
    _, other = other_worker(client, db)
    make_message(conn, ana, content="for d2 (older)", gsm_device_id=other.id)
    anyone = make_message(conn, ana, content="for anyone")
    assert claim(client, headers, device).json()["message"]["id"] == anyone


def test_a_message_meant_for_this_device_is_taken_by_it(client, conn, db, setup, ana):
    headers, device = setup
    mine = make_message(conn, ana, gsm_device_id=device.id)
    assert claim(client, headers, device).json()["message"]["id"] == mine
    assert message_row(db, mine).gsm_device_id == device.id


def test_the_snapshot_number_is_sent_not_the_contacts_current_one(client, conn, setup, ana):
    headers, device = setup
    make_message(conn, ana, phone_number="+639189999999")
    assert claim(client, headers, device).json()["message"]["phone_number"] == "+639189999999"


def test_only_queued_live_gsm_messages_are_claimed(client, conn, db, setup, ana):
    headers, device = setup
    for status in ("sending", "sent", "failed", "received", "delivered"):
        make_message(conn, ana, status=status)
    deleted = make_message(conn, ana)
    db.execute(text("UPDATE messages SET deleted_at = NOW() WHERE id = :i"), {"i": deleted})
    assert claim(client, headers, device).json()["message"] is None


def test_an_expired_lease_fails_the_message_and_never_resends_it(client, conn, db, setup, ana):
    headers, device = setup
    stuck = make_message(conn, ana, content="stuck")
    claim(client, headers, device)
    db.execute(
        text(
            "UPDATE message_lease SET expires_at = UTC_TIMESTAMP() - INTERVAL 1 SECOND WHERE message_id=:i"
        ),
        {"i": stuck},
    )
    later = make_message(conn, ana, content="later")
    body = claim(client, headers, device).json()
    assert body["message"]["id"] == later  # the stuck one is not handed out again
    row = message_row(db, stuck)
    assert row.status == "failed" and "delivery unknown" in row.error_message
    assert lease_row(db, stuck) is None


def test_a_live_lease_is_left_alone(client, conn, db, setup, ana):
    headers, device = setup
    held = make_message(conn, ana)
    claim(client, headers, device)
    claim(client, headers, device)
    assert message_row(db, held).status == "sending" and lease_row(db, held) is not None


def test_a_heartbeat_does_not_fail_what_the_worker_is_still_sending(client, conn, db, setup, ana):
    headers, device = setup
    client.post("/worker/session", json=SESSION, headers=headers)  # the worker starts
    held = make_message(conn, ana)
    claim(client, headers, device)
    for _ in range(3):  # the same process keeps checking in while the send takes its time
        client.post("/worker/session", json=SESSION, headers=headers)
    assert message_row(db, held).status == "sending" and lease_row(db, held) is not None


def test_a_new_session_fails_what_the_worker_left_sending(client, conn, db, setup, ana):
    headers, device = setup
    client.post("/worker/session", json=SESSION, headers=headers)  # the process that crashes
    held = make_message(conn, ana)
    claim(client, headers, device)
    client.post(
        "/worker/session",
        json={**SESSION, "instance_id": "instance-b"},
        headers=headers,
    )
    assert message_row(db, held).status == "failed"
    assert lease_row(db, held) is None


def test_a_session_does_not_touch_another_workers_leases(client, conn, db, setup, ana):
    headers, _ = setup
    other_headers, other_device = other_worker(client, db)
    held = make_message(conn, ana)
    claim(client, other_headers, other_device)
    client.post(
        "/worker/session",
        json={**SESSION, "instance_id": "instance-b"},
        headers=headers,
    )
    assert message_row(db, held).status == "sending"


def test_a_device_that_is_not_the_workers_is_not_found(client, db, setup):
    headers, _ = setup
    theirs = register_device(db, "d2", "+639170000001")
    assert claim(client, headers, theirs).status_code == 404
    r = client.post("/worker/claim", json={"device_id": 999999}, headers=headers)
    assert r.status_code == 404


def test_it_needs_a_worker_token(client, conn, setup):
    _, device = setup
    make_login_user(conn, "boss", "admin")
    body = {"device_id": device.id}
    assert client.post("/worker/claim", json=body).status_code == 401
    assert (
        client.post("/worker/claim", json=body, headers=auth_header(client, "boss")).status_code
        == 401
    )


def test_long_polling_waits_for_a_message_to_arrive(client, conn, setup, ana, monkeypatch):
    headers, device = setup
    clock = {"now": 0.0, "sleeps": 0}
    made = []

    def fake_sleep(seconds):
        clock["now"] += seconds
        clock["sleeps"] += 1
        if clock["sleeps"] == 2:
            made.append(make_message(conn, ana, content="late"))

    monkeypatch.setattr(worker_router, "sleep", fake_sleep)
    monkeypatch.setattr(worker_router, "monotonic", lambda: clock["now"])
    body = claim(client, headers, device, wait_seconds=10).json()
    assert body["message"]["id"] == made[0]
    assert clock["now"] < 10


def test_long_polling_gives_up_after_the_wait_and_is_capped(client, setup, monkeypatch):
    headers, device = setup
    clock = {"now": 0.0}

    def fake_sleep(seconds):
        clock["now"] += seconds

    monkeypatch.setattr(worker_router, "sleep", fake_sleep)
    monkeypatch.setattr(worker_router, "monotonic", lambda: clock["now"])
    assert claim(client, headers, device, wait_seconds=5).json()["message"] is None
    assert 5 <= clock["now"] < 7
    clock["now"] = 0.0
    claim(client, headers, device, wait_seconds=10_000)
    assert settings.worker_long_poll_seconds <= clock["now"] < settings.worker_long_poll_seconds + 2
