"""Register a GSM device: its inbound system agent, the agent's contact and the device row."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.bootstrap import SYSTEM_USER_ID
from app.models import Contact, GsmDevice, User, WorkerAccount
from app.phones import normalize_e164


class DeviceError(Exception):
    pass


PROVIDERS = ("fake", "android", "gsm_modem")


def register_device(
    db: Session,
    name: str,
    serial_port: str,
    phone_number: str,
    *,
    provider: str = "fake",
    config: dict | None = None,
    worker: str | None = None,
) -> GsmDevice:
    """Create ``gsm-<name>`` (an inbound system agent that owns what the device receives) and the
    device itself, both owned by ``system``. ``worker`` is the name of the worker account that
    serves it. Commits; raises ``DeviceError`` on bad input."""
    if provider not in PROVIDERS:
        raise DeviceError(f"unknown provider {provider!r} (one of {', '.join(PROVIDERS)})")
    worker_id = None
    if worker is not None:
        worker_id = db.scalars(
            select(WorkerAccount.id).where(WorkerAccount.name == worker)
        ).one_or_none()
        if worker_id is None:
            raise DeviceError(f"unknown worker {worker!r}")
    try:
        number = normalize_e164(phone_number)
    except ValueError:
        raise DeviceError(f"invalid phone number: {phone_number!r}") from None
    if not name.strip() or not serial_port.strip():
        raise DeviceError("name and serial port are required")
    username = f"gsm-{name}"
    try:
        contact = Contact(name=username, type="entity", owner_id=SYSTEM_USER_ID)
        db.add(contact)
        db.flush()
        agent = User(
            contact_id=contact.id,
            username=username,
            is_system=True,
            agent_direction="inbound",
            login_enabled=False,
            owner_id=SYSTEM_USER_ID,
        )
        db.add(agent)
        db.flush()
        device = GsmDevice(
            name=name,
            serial_port=serial_port,
            phone_number=number,
            provider=provider,
            config=config or {},
            worker_id=worker_id,
            agent_user_id=agent.id,
            owner_id=SYSTEM_USER_ID,
        )
        db.add(device)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if "uq_users_active_username" in str(exc):
            raise DeviceError(f"device {name!r} already exists") from None
        raise
    return device


FAKE_DEVICE_NAME = "fake"


def ensure_fake_device(db: Session) -> GsmDevice | None:
    """For the fake provider only: if no device exists, register a ``fake`` one so a fresh stack can
    send messages without a manual step. Returns it, or None when a device already exists."""
    if db.scalars(select(GsmDevice.id).limit(1)).first() is not None:
        return None
    return register_device(db, FAKE_DEVICE_NAME, "fake", "+639170000000")
