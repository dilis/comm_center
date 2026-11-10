"""POST /worker/inbound and POST /worker/devices/{id}/status."""

import pytest
from sqlalchemy import text

from app.devices import register_device
from tests.api.worker_helpers import make_worker_with_device, other_worker, sign_in
from tests.db.helpers import make_contact, make_phone

pytestmark = pytest.mark.db

SMS = {
    "ref": "r1",
    "sender": "0917 123 4567",
    "content": "hello",
    "received_at": "2026-11-09T08:00:00Z",
}


@pytest.fixture
def setup(client, db):
    headers, device = make_worker_with_device(client, db)
    db.commit()
    return headers, device


def post(client, headers, device, **over):
    return client.post(
        "/worker/inbound", json={"device_id": device.id, **SMS, **over}, headers=headers
    )


def messages(db):
    return db.execute(
        text(
            "SELECT contact_id, phone_number, content, status, owner_id, received_at FROM messages"
        )
    ).all()


def test_a_message_from_an_unknown_sender_creates_a_contact_owned_by_the_agent(client, db, setup):
    headers, device = setup
    r = post(client, headers, device)
    assert r.status_code == 200 and r.json()["stored"] is True
    [m] = messages(db)
    assert (m.phone_number, m.content, m.status, m.owner_id) == (
        "+639171234567",
        "hello",
        "received",
        device.agent_user_id,
    )
    assert str(m.received_at) == "2026-11-09 08:00:00"
    name = db.execute(
        text("SELECT name FROM contacts WHERE id=:i"), {"i": m.contact_id}
    ).scalar_one()
    assert name == "+639171234567"


def test_a_known_sender_reuses_the_contact(client, conn, db, setup):
    headers, device = setup
    cid = make_contact(conn, "Ana")
    make_phone(conn, cid, "+639171234567", is_primary=1)
    post(client, headers, device)
    assert [m.contact_id for m in messages(db)] == [cid]


def test_a_repeated_ref_is_stored_once(client, db, setup):
    headers, device = setup
    first = post(client, headers, device).json()
    again = post(client, headers, device).json()
    assert again == {"stored": False, "duplicate": True, "message_id": first["message_id"]}
    assert len(messages(db)) == 1


def test_the_same_ref_on_another_device_is_a_different_message(client, db, setup):
    headers, device = setup
    other_headers, second = other_worker(client, db, "d2", "+639170000009")
    post(client, headers, device)
    post(client, other_headers, second)
    assert len(messages(db)) == 2


def test_a_sender_that_is_not_a_phone_number_is_dropped_but_remembered(client, db, setup):
    headers, device = setup
    r = post(client, headers, device, sender="PROMO")
    assert r.json() == {"stored": False, "duplicate": False, "message_id": None}
    assert messages(db) == []
    assert post(client, headers, device, sender="PROMO").json()["duplicate"] is True


def test_a_time_without_a_zone_is_taken_as_utc(client, db, setup):
    headers, device = setup
    post(client, headers, device, received_at="2026-11-09T08:00:00")
    assert str(messages(db)[0].received_at) == "2026-11-09 08:00:00"


def test_another_workers_device_is_not_found(client, db, setup):
    headers, _ = setup
    theirs = register_device(db, "d2", "+639170000001")
    assert post(client, headers, theirs).status_code == 404


def test_inbound_needs_a_worker_token(client, setup):
    _, device = setup
    assert client.post("/worker/inbound", json={"device_id": device.id, **SMS}).status_code == 401


def test_a_blank_ref_or_sender_is_rejected(client, setup):
    headers, device = setup
    assert post(client, headers, device, ref="").status_code == 422
    assert post(client, headers, device, sender="").status_code == 422


# --- device status ---


def status(client, headers, device, **body):
    return client.post(f"/worker/devices/{device.id}/status", json=body, headers=headers)


def device_row(db, device):
    return db.execute(
        text("SELECT status, last_error, last_error_at FROM gsm_device WHERE id=:i"),
        {"i": device.id},
    ).one()


def test_status_error_records_the_problem(client, db, setup):
    headers, device = setup
    assert (
        status(client, headers, device, status="error", error="phone unreachable").status_code
        == 204
    )
    row = device_row(db, device)
    assert (row.status, row.last_error) == ("error", "phone unreachable") and row.last_error_at


def test_recovering_keeps_the_last_error_as_history(client, db, setup):
    headers, device = setup
    status(client, headers, device, status="error", error="boom")
    status(client, headers, device, status="online")
    row = device_row(db, device)
    assert (row.status, row.last_error) == ("online", "boom")


def test_a_long_device_error_is_cut_to_fit(client, db, setup):
    headers, device = setup
    status(client, headers, device, status="error", error="x" * 900)
    assert len(device_row(db, device).last_error) == 500


def test_status_values_and_ownership_are_checked(client, db, setup):
    headers, device = setup
    assert status(client, headers, device, status="exploded").status_code == 422
    theirs = register_device(db, "d2", "+639170000001")
    assert status(client, headers, theirs, status="online").status_code == 404
    assert (
        client.post(f"/worker/devices/{device.id}/status", json={"status": "online"}).status_code
        == 401
    )


__all__ = ["sign_in"]
