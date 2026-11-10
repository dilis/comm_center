"""The Android phone end to end: the worker sends through the phone, the phone's signed webhooks
come back to the API, and the message ends up delivered. The phone is scripted; everything else is
the real worker code and the real API."""

import json
import time

import httpx
from comm_center_worker.android import from_config
from comm_center_worker.outbound import RetryPolicy, send_one
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import webhooks
from app.main import app
from tests.worker.conftest import queue, row

POLICY = RetryPolicy(max_attempts=3, backoff_base=0.0)


def webhook(device_id, event):
    body = json.dumps(event).encode()
    ts = str(int(time.time()))
    headers = {
        "X-Timestamp": ts,
        "X-Signature": webhooks.sign(webhooks.device_key(device_id), body, ts),
        "Content-Type": "application/json",
    }
    return TestClient(app).post(f"/devices/{device_id}/webhook", content=body, headers=headers)


def phone_provider(received):
    def handler(request: httpx.Request) -> httpx.Response:
        received.append(json.loads(request.content))
        return httpx.Response(202, json={"id": received[-1]["id"], "state": "Pending"})

    return from_config(
        "http://phone.local:8080", "sms", "pw", timeout=5, transport=httpx.MockTransport(handler)
    )


def test_sent_through_the_phone_then_delivered_by_its_webhook(
    session_factory, commit, ana, api, sleep, device
):
    mid = queue(commit, ana, "hello phone")
    phone_got = []
    assert send_one(api, phone_provider(phone_got), device.id, POLICY, sleep)

    assert phone_got == [
        {
            "id": f"cc-{mid}",
            "textMessage": {"text": "hello phone"},
            "phoneNumbers": ["+639171234567"],
        }
    ]
    assert row(session_factory, mid).status == "sent"
    event = {"event": "sms:delivered", "id": "e1", "payload": {"messageId": f"cc-{mid}"}}
    assert webhook(device.id, event).status_code == 200
    assert row(session_factory, mid).status == "delivered"


def test_a_failure_the_phone_reports_later_fails_the_message_with_its_reason(
    session_factory, commit, ana, api, sleep, device
):
    mid = queue(commit, ana)
    send_one(api, phone_provider([]), device.id, POLICY, sleep)
    event = {
        "event": "sms:failed",
        "id": "e2",
        "payload": {"messageId": f"cc-{mid}", "reason": "RESULT_ERROR_NO_SERVICE"},
    }
    webhook(device.id, event)
    r = row(session_factory, mid)
    assert r.status == "failed" and "NO_SERVICE" in r.error_message


def test_a_message_received_by_the_phone_arrives_by_webhook(session_factory, http_app, device, ana):
    event = {
        "event": "sms:received",
        "id": "e3",
        "payload": {
            "messageId": "m1",
            "message": "hi from a customer",
            "sender": "+639171234567",
            "receivedAt": "2026-11-09T10:00:00+08:00",
        },
    }
    assert webhook(device.id, event).json()["stored"] is True
    assert webhook(device.id, event).json()["duplicate"] is True  # the phone retries; stored once
    with session_factory() as db:
        got = db.execute(
            text("SELECT status, content, contact_id FROM messages WHERE content LIKE 'hi from%'")
        ).all()
    assert len(got) == 1 and got[0].status == "received" and got[0].contact_id == ana
