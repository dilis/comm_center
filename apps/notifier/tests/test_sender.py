"""comm_center_notifier.sender without a database or a network."""

import base64
import os
from types import SimpleNamespace

import pytest
import requests
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from pywebpush import WebPushException, webpush

from comm_center_notifier import sender
from comm_center_notifier.config import settings


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def vapid_pair() -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    return b64(public), b64(key.private_numbers().private_value.to_bytes(32, "big"))


@pytest.fixture
def vapid(monkeypatch):
    public, private = vapid_pair()
    monkeypatch.setattr(settings, "vapid_public_key", public)
    monkeypatch.setattr(settings, "vapid_private_key", private)
    monkeypatch.setattr(settings, "vapid_subject", "mailto:admin@example.com")
    return public, private


def test_push_is_on_only_with_all_three_settings(monkeypatch):
    for name in ("vapid_public_key", "vapid_private_key", "vapid_subject"):
        monkeypatch.setattr(settings, name, "")
    assert sender.push_enabled() is False
    monkeypatch.setattr(settings, "vapid_private_key", "priv")
    assert sender.push_enabled() is False  # the subject is missing
    monkeypatch.setattr(settings, "vapid_subject", "mailto:a@example.com")
    assert sender.push_enabled() is True  # the public key is the API's business, not ours


def test_the_keys_the_api_generates_sign_a_real_push_request(vapid, tmp_path, monkeypatch):
    """Build (not send) a full request, so the key format is the one pywebpush reads."""
    monkeypatch.chdir(tmp_path)  # curl=True leaves the encrypted body in ./encrypted.data
    key = ec.generate_private_key(ec.SECP256R1())
    point = key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    command = webpush(
        {"endpoint": "https://push.example.com/send/abc", "keys": {"p256dh": b64(point), "auth": b64(os.urandom(16))}},
        data="{}",
        vapid_private_key=vapid[1],
        vapid_claims={"sub": settings.vapid_subject},
        curl=True,
    )
    assert "vapid" in command.lower()


def test_one_message_names_its_sender_and_carries_no_sms_text():
    assert sender.payload_for(1, ["Maria Santos"], last_message_id=7) == {
        "title": "New message",
        "body": "From Maria Santos",
        "url": "/messages?direction=received",
        "tag": "message-7",
    }


@pytest.mark.parametrize(
    ("count", "senders", "title", "body"),
    [
        (3, ["Maria"], "3 new messages", "From Maria"),
        (2, ["Maria", "Jose"], "2 new messages", "From Maria and Jose"),
        (5, ["Maria", "Jose", "Ana"], "5 new messages", "From Maria, Jose and Ana"),
        (9, ["Maria", "Jose", "Ana", "Ben"], "9 new messages", "From Maria, Jose, Ana and others"),
    ],
)
def test_several_messages_make_one_notification(count, senders, title, body):
    payload = sender.payload_for(count, senders, last_message_id=12)
    assert (payload["title"], payload["body"], payload["tag"]) == (title, body, "message-12")


def test_retries_wait_longer_each_time(monkeypatch):
    monkeypatch.setattr(settings, "push_retry_base_seconds", 30)
    assert [sender.retry_delay(n) for n in (1, 2, 3, 4)] == [30, 60, 120, 240]


def test_send_push_passes_the_target_the_payload_and_the_claims(vapid, monkeypatch):
    seen = {}
    monkeypatch.setattr(sender, "webpush", lambda **kw: seen.update(kw))
    sender.send_push(sender.Target("https://p/1", "k", "a"), {"title": "t"})
    assert seen["subscription_info"] == {"endpoint": "https://p/1", "keys": {"p256dh": "k", "auth": "a"}}
    assert seen["data"] == '{"title": "t"}'
    assert seen["vapid_private_key"] == vapid[1]
    assert seen["vapid_claims"] == {"sub": "mailto:admin@example.com"}
    assert seen["ttl"] > 0


@pytest.mark.parametrize("status", [404, 410])
def test_a_subscription_the_service_forgot_is_gone(vapid, monkeypatch, status):
    def boom(**kw):
        raise WebPushException("gone", response=SimpleNamespace(status_code=status))

    monkeypatch.setattr(sender, "webpush", boom)
    with pytest.raises(sender.PushGone):
        sender.send_push(sender.Target("https://p/1", "k", "a"), {})


@pytest.mark.parametrize("status", [500, 502, 429, None])
def test_temporary_failures_are_worth_retrying(vapid, monkeypatch, status):
    response = SimpleNamespace(status_code=status) if status else None

    def boom(**kw):
        raise WebPushException("nope", response=response)

    monkeypatch.setattr(sender, "webpush", boom)
    with pytest.raises(sender.PushError) as info:
        sender.send_push(sender.Target("https://p/1", "k", "a"), {})
    assert info.value.retryable and not isinstance(info.value, sender.PushGone)


@pytest.mark.parametrize("status", [400, 401, 403, 413])
def test_a_rejection_will_fail_every_time_so_it_is_not_retried(vapid, monkeypatch, status):
    def boom(**kw):
        raise WebPushException("no", response=SimpleNamespace(status_code=status))

    monkeypatch.setattr(sender, "webpush", boom)
    with pytest.raises(sender.PushRejected) as info:
        sender.send_push(sender.Target("https://p/1", "k", "a"), {})
    assert not info.value.retryable and not isinstance(info.value, sender.PushGone)


def test_a_network_error_is_temporary(vapid, monkeypatch):
    def boom(**kw):
        raise requests.ConnectionError("no route")

    monkeypatch.setattr(sender, "webpush", boom)
    with pytest.raises(sender.PushError) as info:
        sender.send_push(sender.Target("https://p/1", "k", "a"), {})
    assert info.value.retryable
