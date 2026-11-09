"""Signing keys and signature checks for webhooks from the Android gateway app.

Each device has its own signing key, derived from the server's ``WEBHOOK_SECRET`` and the device id,
so nothing per device is stored: print it with ``webhook-info`` and paste it into the app (Settings,
Webhooks, Signing Key). The app signs each request with HMAC-SHA256 over the raw body followed by
the timestamp (``X-Timestamp``, Unix seconds) and sends the hex digest in ``X-Signature``.
"""

import hashlib
import hmac
import time

from app.config import settings

SIGNATURE_WINDOW_SECONDS = 300


def device_key(device_id: int) -> str:
    """The signing key for a device. Changing ``WEBHOOK_SECRET`` changes every key."""
    return hmac.new(
        settings.webhook_secret.encode(), f"webhook:device:{device_id}".encode(), hashlib.sha256
    ).hexdigest()


def sign(key: str, body: bytes, timestamp: str) -> str:
    return hmac.new(key.encode(), body + timestamp.encode(), hashlib.sha256).hexdigest()


def verify(
    device_id: int,
    body: bytes,
    timestamp: str | None,
    signature: str | None,
    now: float | None = None,
) -> bool:
    """True when the signature matches this device's key and the timestamp is recent."""
    if not timestamp or not signature:
        return False
    try:
        sent_at = int(timestamp)
    except ValueError:
        return False
    if abs((time.time() if now is None else now) - sent_at) > SIGNATURE_WINDOW_SECONDS:
        return False
    expected = sign(device_key(device_id), body, timestamp)
    return hmac.compare_digest(expected, signature.strip().lower())
