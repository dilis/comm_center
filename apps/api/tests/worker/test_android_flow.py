"""The Android phone end to end: the worker sends through the phone, the phone's signed webhooks
come back to the API, and the message ends up delivered. The phone is scripted; everything else is
the real worker code and the real API."""

import json
import time

import httpx
from comm_center_worker.android import from_device
from comm_center_worker.outbound import RetryPolicy, send_one
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import webhooks
from app.devices import register_device
from app.main import app
from tests.worker.conftest import WORKER_NAME, queue, row

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


def android_device(session_factory):
    with session_factory() as db:
        return register_device(
            db, "phone1", "-", "+639170000000", provider="android", worker=WORKER_NAME,
            config={
                "base_url": "http://phone.local:8080",
                "username_ref": "PHONE1_USERNAME",
                "password_ref": "PHONE1_PASSWORD",
            },
        )  # fmt: skip


def phone_provider(device, received):
    def handler(request: httpx.Request) -> httpx.Response:
        received.append(json.loads(request.content))
        return httpx.Response(202, json={"id": received[-1]["id"], "state": "Pending"})

    config = {"id": device.id, "name": device.name, "config": device.config}
    env = {"PHONE1_USERNAME": "sms", "PHONE1_PASSWORD": "pw"}
    return from_device(config, env, timeout=5, transport=httpx.MockTransport(handler))


def test_sent_through_the_phone_then_delivered_by_its_webhook(
    session_factory, commit, ana, api, sleep
):
    device = android_device(session_factory)
    mid = queue(commit, ana, "hello phone")
    phone_got = []
    assert send_one(api, phone_provider(device, phone_got), device.id, POLICY, sleep)

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
    session_factory, commit, ana, api, sleep
):
    device = android_device(session_factory)
    mid = queue(commit, ana)
    send_one(api, phone_provider(device, []), device.id, POLICY, sleep)
    event = {
        "event": "sms:failed",
        "id": "e2",
        "payload": {"messageId": f"cc-{mid}", "reason": "RESULT_ERROR_NO_SERVICE"},
    }
    webhook(device.id, event)
    r = row(session_factory, mid)
    assert r.status == "failed" and "NO_SERVICE" in r.error_message


def test_a_message_received_by_the_phone_arrives_by_webhook(session_factory, http_app, worker, ana):
    device = android_device(session_factory)
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
