"""GSM devices and their workers.

A device is served by one worker program. The worker signs in as the device's inbound system agent
(``gsm-<name>``), using a secret stored as a hash on that agent. The API does not know what kind of
device it is or how to reach it: that is the worker's own configuration.
"""

import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import security
from app.bootstrap import SYSTEM_USER_ID
from app.models import Contact, GsmDevice, User
from app.phones import normalize_e164

AGENT_PREFIX = "gsm-"
MIN_SECRET_LENGTH = 16


class DeviceError(Exception):
    pass


def new_secret() -> str:
    return secrets.token_urlsafe(32)


def _check_secret(secret: str) -> None:
    if len(secret) < MIN_SECRET_LENGTH:
        raise DeviceError(f"the secret must be at least {MIN_SECRET_LENGTH} characters")


def register_device(
    db: Session, name: str, phone_number: str, *, secret: str | None = None
) -> GsmDevice:
    """Create ``gsm-<name>`` (an inbound system agent that owns what the device receives, and the
    account its worker signs in with) and the device itself, both owned by ``system``. With a
    ``secret`` the worker can sign in right away; without one, set it with ``set_device_secret``.
    Commits; raises ``DeviceError`` on bad input."""
    name = name.strip()
    if not name or len(name) > 64 - len(AGENT_PREFIX):
        raise DeviceError(f"a device name of 1 to {64 - len(AGENT_PREFIX)} characters is required")
    try:
        number = normalize_e164(phone_number, strict=False)
    except ValueError:
        raise DeviceError(f"invalid phone number: {phone_number!r}") from None
    if secret is not None:
        _check_secret(secret)
    username = AGENT_PREFIX + name
    try:
        contact = Contact(first_name=username, type="entity", owner_id=SYSTEM_USER_ID)
        db.add(contact)
        db.flush()
        agent = User(
            contact_id=contact.id,
            username=username,
            password_hash=security.hash_password(secret) if secret else None,
            is_system=True,
            agent_direction="inbound",
            login_enabled=False,  # the worker uses /worker/token; the web app stays closed to it
            owner_id=SYSTEM_USER_ID,
        )
        db.add(agent)
        db.flush()
        device = GsmDevice(
            name=name, phone_number=number, agent_user_id=agent.id, owner_id=SYSTEM_USER_ID
        )
        db.add(device)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if "uq_users_active_username" in str(exc):
            raise DeviceError(f"device {name!r} already exists") from None
        raise
    return device


def _device_by_name(db: Session, name: str) -> GsmDevice:
    device = db.scalars(select(GsmDevice).where(GsmDevice.name == name)).first()
    if device is None:
        raise DeviceError(f"unknown device {name!r}")
    return device


def set_device_secret(db: Session, name: str, secret: str | None = None) -> str:
    """Give the device's worker a new secret (a random one unless given), replacing the old. It
    cannot be shown again. Commits."""
    if secret is not None:
        _check_secret(secret)
    secret = secret or new_secret()
    device = _device_by_name(db, name)
    agent = db.get(User, device.agent_user_id)
    agent.password_hash = security.hash_password(secret)
    db.commit()
    return secret


def ensure_device(db: Session, name: str, phone_number: str, secret: str) -> tuple[GsmDevice, bool]:
    """Create the device with this secret, or give an existing one this secret (for deployments that
    set the secret from the environment). Returns it and whether it was new. Commits."""
    _check_secret(secret)
    existing = db.scalars(select(GsmDevice).where(GsmDevice.name == name)).first()
    if existing is None:
        return register_device(db, name, phone_number, secret=secret), True
    set_device_secret(db, name, secret)
    return existing, False


def authenticate_device(db: Session, username: str, secret: str) -> GsmDevice | None:
    """The device whose agent has this username and secret; always one hash check, so timing does
    not reveal which usernames exist."""
    agent = db.scalars(
        select(User).where(
            User.username == username,
            User.is_system.is_(True),
            User.agent_direction == "inbound",
            User.is_active.is_(True),
        )
    ).first()
    hash_ = agent.password_hash if agent and agent.password_hash else security.DUMMY_HASH
    valid = security.verify_password(hash_, secret)
    if not (agent and agent.password_hash and valid):
        return None
    return db.scalars(select(GsmDevice).where(GsmDevice.agent_user_id == agent.id)).first()
