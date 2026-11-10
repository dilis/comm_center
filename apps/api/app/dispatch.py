"""The outbound queue as the worker API sees it: claim a message under a lease, report its result.

Messages are never re-sent. A message whose worker went silent (its lease ran out, or the worker
started a new session) is failed for a person to decide, because it may already have gone out.
"""

from datetime import timedelta

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.config import settings
from app.models import GsmDevice, Message, MessageLease

MAX_ERROR_LENGTH = 1000
LEASE_EXPIRED = "worker stopped responding while sending; delivery unknown"
WORKER_RESTARTED = "worker restarted while sending; delivery unknown"


def _fail_leases(db: Session, lease_ids: list[int], error: str) -> int:
    if not lease_ids:
        return 0
    db.execute(
        update(Message)
        .where(Message.id.in_(lease_ids), Message.status == "sending")
        .values(status="failed", error_message=error)
    )
    db.execute(delete(MessageLease).where(MessageLease.message_id.in_(lease_ids)))
    return len(lease_ids)


def _lock_leases(db: Session, condition) -> list[int]:
    """Lock the leases matching ``condition`` and return their message ids.

    The matching rows are found with a plain read and then locked by primary key. A locking range
    read (``WHERE expires_at < now FOR UPDATE``) takes gap locks, which block other workers'
    lease inserts and deadlock under concurrent claims."""
    candidates = list(db.scalars(select(MessageLease.message_id).where(condition)))
    if not candidates:
        return []
    return list(
        db.scalars(
            select(MessageLease.message_id)
            .where(MessageLease.message_id.in_(candidates), condition)
            .with_for_update(skip_locked=True)
        )
    )


def expire_leases(db: Session) -> int:
    """Fail every message whose lease has run out. Returns how many."""
    return _fail_leases(db, _lock_leases(db, MessageLease.expires_at < utcnow()), LEASE_EXPIRED)


def fail_device_leases(db: Session, device_id: int) -> int:
    """A worker that opens a new session cannot still be sending what it held before."""
    return _fail_leases(db, _lock_leases(db, MessageLease.device_id == device_id), WORKER_RESTARTED)


def claim_next(db: Session, device: GsmDevice) -> Message | None:
    """Take the oldest queued message that no other claimer holds (``FOR UPDATE SKIP LOCKED``) and
    that this device may send (one meant for another device is skipped), mark it ``sending`` on this
    device and lease it. The caller commits."""
    message = db.scalars(
        select(Message)
        .where(
            Message.status == "queued",  # soft-deleted rows excluded
            Message.channel == "gsm",
            or_(Message.gsm_device_id.is_(None), Message.gsm_device_id == device.id),
        )
        .order_by(Message.created_at, Message.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if message is None:
        return None
    message.status = "sending"
    message.gsm_device_id = device.id
    db.add(
        MessageLease(
            message_id=message.id,
            device_id=device.id,
            expires_at=utcnow() + timedelta(seconds=settings.worker_lease_seconds),
        )
    )
    db.flush()
    return message


def held_lease(db: Session, device: GsmDevice, message_id: int) -> MessageLease | None:
    lease = db.scalars(
        select(MessageLease).where(MessageLease.message_id == message_id).with_for_update()
    ).one_or_none()
    return lease if lease and lease.device_id == device.id else None


def finish(db: Session, lease: MessageLease, status: str, error: str | None) -> None:
    """Record the outcome and release the lease. A core UPDATE, so it also reaches a message that
    was soft-deleted while it was being sent. Only a message still ``sending`` changes: if the phone
    already reported (delivered, failed) before the worker did, that report stands. The caller
    commits."""
    values: dict = {
        "status": status,
        "error_message": error[:MAX_ERROR_LENGTH] if error else None,
    }
    if status == "sent":
        values["sent_at"] = utcnow()
    db.execute(
        update(Message)
        .where(Message.id == lease.message_id, Message.status == "sending")
        .values(**values)
    )
    db.delete(lease)
    db.flush()


GATEWAY_ID_PREFIX = "cc-"


def gateway_message_id(message_id: int) -> str:
    """The id we give the Android gateway for a message, so its delivery events can be matched."""
    return f"{GATEWAY_ID_PREFIX}{message_id}"


def parse_gateway_message_id(value: object) -> int | None:
    if not isinstance(value, str) or not value.startswith(GATEWAY_ID_PREFIX):
        return None
    digits = value[len(GATEWAY_ID_PREFIX) :]
    return int(digits) if digits.isascii() and digits.isdigit() else None


def apply_delivery_report(
    db: Session, device_id: int, message_id: int, status: str, error: str | None = None
) -> bool:
    """Apply what the phone reports about a message it was given: ``delivered`` or ``failed``.
    Only a message of this device that is ``sending`` or ``sent`` changes (``delivered`` and
    ``failed`` are final). Returns whether it did. The caller commits."""
    values: dict = {"status": status}
    if status == "failed":
        values["error_message"] = (error or "the phone reported a failure")[:MAX_ERROR_LENGTH]
    result = db.execute(
        update(Message)
        .where(
            Message.id == message_id,
            Message.gsm_device_id == device_id,
            Message.status.in_(("sending", "sent")),
        )
        .values(**values)
    )
    return result.rowcount > 0
