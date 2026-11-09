"""Signing keys and signature checks for the Android gateway's webhooks (no database)."""

import hashlib
import hmac

from app import webhooks

BODY = b'{"event":"sms:received"}'


def test_every_device_has_its_own_stable_key():
    assert webhooks.device_key(1) == webhooks.device_key(1)
    assert webhooks.device_key(1) != webhooks.device_key(2)
    assert len(webhooks.device_key(1)) >= 32


def test_the_key_depends_on_the_servers_webhook_secret(monkeypatch):
    before = webhooks.device_key(1)
    monkeypatch.setattr(webhooks.settings, "webhook_secret", "another-secret-another-secret-xx")
    assert webhooks.device_key(1) != before


def test_the_signature_is_hmac_sha256_of_body_then_timestamp():
    key = webhooks.device_key(7)
    expected = hmac.new(key.encode(), BODY + b"1700000000", hashlib.sha256).hexdigest()
    assert webhooks.sign(key, BODY, "1700000000") == expected


def test_a_good_signature_verifies():
    sig = webhooks.sign(webhooks.device_key(7), BODY, "1700000000")
    assert webhooks.verify(7, BODY, "1700000000", sig, now=1700000000)


def test_the_wrong_device_a_changed_body_or_a_changed_time_do_not_verify():
    sig = webhooks.sign(webhooks.device_key(7), BODY, "1700000000")
    assert not webhooks.verify(8, BODY, "1700000000", sig, now=1700000000)
    assert not webhooks.verify(7, BODY + b" ", "1700000000", sig, now=1700000000)
    assert not webhooks.verify(7, BODY, "1700000001", sig, now=1700000000)


def test_a_timestamp_outside_five_minutes_is_refused_either_way():
    sig = webhooks.sign(webhooks.device_key(7), BODY, "1700000000")
    assert webhooks.verify(7, BODY, "1700000000", sig, now=1700000000 + 299)
    assert not webhooks.verify(7, BODY, "1700000000", sig, now=1700000000 + 301)
    assert not webhooks.verify(7, BODY, "1700000000", sig, now=1700000000 - 301)


def test_missing_or_malformed_headers_never_verify_and_never_raise():
    good = webhooks.sign(webhooks.device_key(7), BODY, "1700000000")
    for timestamp, signature in [
        (None, good), ("1700000000", None), ("", good), ("not-a-number", good),
        ("1700000000", "zz"), ("1700000000", ""), ("1700000000", good.upper() + "x"),
    ]:  # fmt: skip
        assert not webhooks.verify(7, BODY, timestamp, signature, now=1700000000)


def test_the_hex_may_be_upper_case():
    sig = webhooks.sign(webhooks.device_key(7), BODY, "1700000000").upper()
    assert webhooks.verify(7, BODY, "1700000000", sig, now=1700000000)
