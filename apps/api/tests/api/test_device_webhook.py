"""POST /devices/{id}/webhook: what the Android gateway app tells us, signed per device."""

import json
import time

import pytest
from sqlalchemy import text

from app import webhooks
from app.devices import register_device
from tests.db.helpers import make_contact, make_message, make_phone

pytestmark = pytest.mark.db


@pytest.fixture
def phone(db):
    device = register_device(db, "phone1", "+639170000000")
    db.commit()
    return device


def post(client, device_id, payload, *, key=None, timestamp=None, signature=None, raw=None):
    body = raw if raw is not None else json.dumps(payload).encode()
    ts = str(int(time.time())) if timestamp is None else timestamp
    key = webhooks.device_key(device_id) if key is None else key
    headers = {
        "X-Timestamp": ts,
        "X-Signature": signature if signature is not None else webhooks.sign(key, body, ts),
        "Content-Type": "application/json",
    }
    return client.post(f"/devices/{device_id}/webhook", content=body, headers=headers)


def received(**over):
    payload = {
        "messageId": "abc123",
        "message": "hello there",
        "sender": "0917 123 4567",
        "recipient": "+639170000000",
        "simNumber": 1,
        "receivedAt": "2026-11-09T15:46:11.000+08:00",
    }
    return {
        "deviceId": "dev",
        "event": "sms:received",
        "id": "evt-1",
        "payload": {**payload, **over},
        "webhookId": "wh",
    }


def messages(db):
    return db.execute(
        text(
            "SELECT contact_id, phone_number, content, status, owner_id, received_at FROM messages"
        )
    ).all()


# --- authentication ---


def test_a_missing_or_wrong_signature_is_refused(client, phone, db):
    assert client.post(f"/devices/{phone.id}/webhook", content=b"{}").status_code == 401
    assert post(client, phone.id, received(), signature="0" * 64).status_code == 401
    assert post(client, phone.id, received(), key="not-the-key").status_code == 401
    assert messages(db) == []


def test_a_stale_timestamp_is_refused(client, phone, db):
    old = str(int(time.time()) - 3600)
    assert post(client, phone.id, received(), timestamp=old).status_code == 401
    assert messages(db) == []


def test_the_key_of_another_device_does_not_work(client, db, phone):
    other = register_device(db, "phone2", "+639170000001")
    db.commit()
    key_of_other = webhooks.device_key(other.id)
    assert post(client, phone.id, received(), key=key_of_other).status_code == 401


def test_an_unknown_device_looks_the_same_as_a_bad_signature(client, db, phone):
    unknown = post(client, 999999, received())
    bad = post(client, phone.id, received(), signature="0" * 64)
    assert {unknown.status_code, bad.status_code} == {401}
    assert unknown.json() == bad.json()


# --- received messages ---


def test_a_received_message_is_stored_like_any_inbound_message(client, phone, db):
    r = post(client, phone.id, received())
    assert r.status_code == 200 and r.json()["stored"] is True
    [m] = messages(db)
    assert (m.phone_number, m.content, m.status, m.owner_id) == (
        "+639171234567", "hello there", "received", phone.agent_user_id,
    )  # fmt: skip
    assert str(m.received_at) == "2026-11-09 07:46:11"  # +08:00 converted to UTC


def test_a_known_sender_reuses_the_contact(client, conn, phone, db):
    cid = make_contact(conn, "Ana")
    make_phone(conn, cid, "+639171234567", is_primary=1)
    post(client, phone.id, received())
    assert [m.contact_id for m in messages(db)] == [cid]


def test_the_same_event_delivered_twice_is_stored_once(client, phone, db):
    first = post(client, phone.id, received()).json()
    again = post(client, phone.id, received()).json()
    assert again["duplicate"] is True and again["message_id"] == first["message_id"]
    assert len(messages(db)) == 1


def test_two_different_events_with_the_same_text_are_two_messages(client, phone, db):
    post(client, phone.id, received())
    second = received()
    second["id"] = "evt-2"
    post(client, phone.id, second)
    assert len(messages(db)) == 2


def test_an_older_payload_with_phoneNumber_is_understood(client, phone, db):
    payload = received()
    del payload["payload"]["sender"]
    payload["payload"]["phoneNumber"] = "+639171234567"
    assert post(client, phone.id, payload).json()["stored"] is True


def test_a_sender_that_is_not_a_phone_number_is_acknowledged_but_dropped(client, phone, db):
    r = post(client, phone.id, received(sender="PROMO"))
    assert r.status_code == 200 and r.json()["stored"] is False
    assert messages(db) == []


def test_a_received_event_without_text_or_sender_is_a_bad_request(client, phone):
    payload = received()
    del payload["payload"]["message"]
    assert post(client, phone.id, payload).status_code == 400


# --- delivery status of what we sent ---


@pytest.fixture
def sent(conn, phone):
    """An outbound message this phone accepted (status sent)."""
    cid = make_contact(conn, "Ana")
    make_phone(conn, cid, "+639171234567", is_primary=1)
    mid = make_message(conn, cid, status="sent", gsm_device_id=phone.id)
    return mid


def event(name, mid, **payload):
    return {
        "deviceId": "dev",
        "event": name,
        "id": f"{name}-{mid}",
        "payload": {"messageId": f"cc-{mid}", **payload},
        "webhookId": "wh",
    }


def status_of(db, mid):
    return db.execute(
        text("SELECT status, error_message FROM messages WHERE id=:i"), {"i": mid}
    ).one()


def test_delivered_marks_a_sent_message_delivered(client, phone, db, sent):
    assert post(client, phone.id, event("sms:delivered", sent)).status_code == 200
    assert status_of(db, sent).status == "delivered"


def test_delivered_arriving_before_the_worker_reported_still_counts(client, conn, phone, db):
    cid = make_contact(conn, "Bo")
    mid = make_message(conn, cid, status="sending", gsm_device_id=phone.id)
    post(client, phone.id, event("sms:delivered", mid))
    assert status_of(db, mid).status == "delivered"


def test_failed_marks_a_sent_message_failed_with_the_reason(client, phone, db, sent):
    post(client, phone.id, event("sms:failed", sent, reason="RESULT_ERROR_GENERIC_FAILURE"))
    row = status_of(db, sent)
    assert row.status == "failed" and "RESULT_ERROR_GENERIC_FAILURE" in row.error_message


def test_failed_without_a_reason_still_fails_it(client, phone, db, sent):
    post(client, phone.id, event("sms:failed", sent))
    assert status_of(db, sent).status == "failed"


def test_delivered_is_final_and_a_late_failure_does_not_undo_it(client, phone, db, sent):
    post(client, phone.id, event("sms:delivered", sent))
    post(client, phone.id, event("sms:failed", sent, reason="late"))
    assert status_of(db, sent).status == "delivered"


def test_a_failed_message_is_not_resurrected_by_delivered(client, conn, phone, db):
    cid = make_contact(conn, "Cy")
    mid = make_message(conn, cid, status="failed", gsm_device_id=phone.id, error_message="x")
    post(client, phone.id, event("sms:delivered", mid))
    assert status_of(db, mid).status == "failed"


def test_sent_events_change_nothing(client, phone, db, sent):
    assert post(client, phone.id, event("sms:sent", sent)).status_code == 200
    assert status_of(db, sent).status == "sent"


def test_a_message_of_another_device_is_left_alone(client, db, conn, phone):
    other = register_device(db, "phone2", "+639170000001")
    db.commit()
    cid = make_contact(conn, "Di")
    mid = make_message(conn, cid, status="sent", gsm_device_id=other.id)
    r = post(client, phone.id, event("sms:delivered", mid))
    assert r.status_code == 200 and r.json()["ignored"] is True
    assert status_of(db, mid).status == "sent"


@pytest.mark.parametrize("message_id", ["abc", "cc-", "cc-notanumber", "cc-999999", "", None])
def test_ids_that_are_not_ours_are_ignored_not_errors(client, phone, message_id):
    payload = event("sms:delivered", 1)
    payload["payload"]["messageId"] = message_id
    r = post(client, phone.id, payload)
    assert r.status_code == 200 and r.json()["ignored"] is True


def test_other_events_are_acknowledged_and_ignored(client, phone):
    for name in ("system:ping", "app:started", "sms:batch:received", "mms:received", "nonsense"):
        r = post(client, phone.id, {"event": name, "id": "x", "payload": {}})
        assert r.status_code == 200 and r.json()["ignored"] is True


def test_a_signed_body_that_is_not_json_is_a_bad_request(client, phone):
    assert post(client, phone.id, None, raw=b"not json").status_code == 400
    assert post(client, phone.id, None, raw=b"[1,2]").status_code == 400
