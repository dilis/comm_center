"""Web Push, the API's side: whether it is on, new key pairs, and who may be notified about a received
message. The API only queues (``app.push_outbox``); the notifier (``apps/notifier``) sends, and is the
only one that holds the private key.
"""

import base64
import hashlib

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authz import effective_permissions
from app.config import settings
from app.models import PushSubscription, User


def endpoint_hash(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode()).hexdigest()


def push_enabled() -> bool:
    """Push is on when the browsers' public key is set. The notifier decides for itself whether it
    can send (it needs the private key and the subject)."""
    return bool(settings.vapid_public_key)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def new_vapid_keys() -> tuple[str, str]:
    """A fresh (public, private) pair in the URL-safe base64 the browser and pywebpush read."""
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_numbers().private_value.to_bytes(32, "big")
    public = key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    return _b64(public), _b64(private)


def inbound_recipients(db: Session) -> list[int]:
    """Subscribed people who can see received messages (``read_all`` or ``read_received``), read
    from the database now so a removed permission stops the pushes at once."""
    candidates = db.scalars(
        select(User.id).where(
            User.id.in_(select(PushSubscription.user_id)),
            User.is_system.is_(False),
            User.login_enabled.is_(True),
        )
    ).all()
    return [
        user_id
        for user_id in candidates
        if (perms := effective_permissions(db, user_id))
        and (("messages", "read_all") in perms or ("messages", "read_received") in perms)
    ]
