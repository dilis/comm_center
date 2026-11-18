"""app/push.py without a database or a network."""

import base64
import subprocess
import sys

from app import push
from app.config import settings


def test_endpoint_hash_is_a_stable_sha256_hex():
    h = push.endpoint_hash("https://push.example.com/send/abc")
    assert len(h) == 64 and h == push.endpoint_hash("https://push.example.com/send/abc")
    assert h != push.endpoint_hash("https://push.example.com/send/abd")


def test_push_is_on_when_the_public_key_is_set(monkeypatch):
    monkeypatch.setattr(settings, "vapid_public_key", "")
    assert push.push_enabled() is False
    monkeypatch.setattr(settings, "vapid_public_key", "pub")
    assert push.push_enabled() is True  # the private key is the notifier's business


def test_new_vapid_keys_are_url_safe_and_the_public_key_is_an_uncompressed_point():
    public, private = push.new_vapid_keys()
    assert len(base64.urlsafe_b64decode(public + "==")) == 65  # what applicationServerKey wants
    assert len(base64.urlsafe_b64decode(private + "==")) == 32
    assert "=" not in public + private and push.new_vapid_keys() != (public, private)


def test_the_api_never_loads_the_push_sending_library():
    """Sending is the notifier's job: the API holds no private key and cannot reach a push service."""
    code = (
        "import sys, app.main, app.push, app.push_outbox, app.inbound\n"
        "sys.exit(1 if 'pywebpush' in sys.modules else 0)"
    )
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0
