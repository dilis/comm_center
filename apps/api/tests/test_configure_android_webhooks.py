import json

import httpx
import pytest

from app import webhooks
from scripts.configure_android_webhooks import (
    configure_signing_key,
    configure_webhooks,
    delete_webhook,
    device_id_from_url,
)

WEBHOOK_URL = "https://sms.example.com/api/devices/17/webhook"


def test_configure_webhooks_registers_only_missing_events():
    calls = []
    posted = []

    def handle(request):
        calls.append((request.method, request.url.path))
        if request.method == "POST":
            posted.append(json.loads(request.content))
        if request.method == "GET":
            return httpx.Response(
                200,
                json=[{"id": "cc-received", "url": WEBHOOK_URL, "event": "sms:received"}],
            )
        return httpx.Response(201, json={})

    with httpx.Client(
        base_url="http://gateway", transport=httpx.MockTransport(handle)
    ) as client:
        configured = configure_webhooks(client, WEBHOOK_URL, ("sms:received", "sms:failed"))

    assert configured == {"sms:received": False, "sms:failed": True}
    assert posted == [{"id": "cc-failed", "url": WEBHOOK_URL, "event": "sms:failed"}]
    assert calls == [
        ("GET", "/webhooks"),
        ("POST", "/webhooks"),
    ]


def test_configure_signing_key_sets_key_for_device_in_webhook_url():
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={})

    with httpx.Client(
        base_url="http://gateway", transport=httpx.MockTransport(handle)
    ) as client:
        device_id = configure_signing_key(client, WEBHOOK_URL)

    assert device_id == 17
    assert requests[0].method == "PATCH"
    assert requests[0].url.path == "/settings"
    assert json.loads(requests[0].content) == {
        "webhooks": {"signing_key": webhooks.device_key(17)}
    }


def test_delete_webhook_deletes_by_id():
    calls = []

    def handle(request):
        calls.append((request.method, request.url.raw_path.decode()))
        return httpx.Response(204)

    with httpx.Client(
        base_url="http://gateway", transport=httpx.MockTransport(handle)
    ) as client:
        delete_webhook(client, "abc/123")

    assert calls == [("DELETE", "/webhooks/abc%2F123")]


def test_delete_webhook_reports_a_gateway_error():
    with httpx.Client(
        base_url="http://gateway",
        transport=httpx.MockTransport(lambda request: httpx.Response(404)),
    ) as client, pytest.raises(httpx.HTTPStatusError):
        delete_webhook(client, "missing")


@pytest.mark.parametrize(
    "url",
    [
        "ftp://sms.example.com/api/devices/17/webhook",
        "https://sms.example.com/api/devices/nope/webhook",
        "https://sms.example.com/webhook",
    ],
)
def test_device_id_requires_an_http_comm_center_webhook_url(url):
    with pytest.raises(ValueError):
        device_id_from_url(url)


def test_device_id_allows_plain_http():
    assert device_id_from_url("http://192.168.1.20:8000/devices/17/webhook") == 17
