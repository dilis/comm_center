"""The outbound queue as the worker API sees it: claim a message under a lease, report its result.

Messages are never re-sent. A message whose worker went silent (its lease ran out, or the worker
started a new session) is failed for a person to decide, because it may already have gone out.
"""

from datetime import timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.config import settings
from app.models import Message, MessageLease, WorkerAccount

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


def expire_leases(db: Session) -> int:
    """Fail every message whose lease has run out. Returns how many."""
    ids = list(
        db.scalars(
            select(MessageLease.message_id)
            .where(MessageLease.expires_at < utcnow())
            .with_for_update(skip_locked=True)
        )
    )
    return _fail_leases(db, ids, LEASE_EXPIRED)


def fail_worker_leases(db: Session, worker_id: int) -> int:
    """A worker that opens a new session cannot still be sending what it held before."""
    ids = list(
        db.scalars(
            select(MessageLease.message_id)
            .where(MessageLease.worker_id == worker_id)
            .with_for_update(skip_locked=True)
        )
    )
    return _fail_leases(db, ids, WORKER_RESTARTED)


def claim_next(db: Session, worker: WorkerAccount, device_id: int) -> Message | None:
    """Take the oldest queued message that no other claimer holds (``FOR UPDATE SKIP LOCKED``),
    mark it ``sending`` on this device and lease it to the worker. The caller commits."""
    message = db.scalars(
        select(Message)
        .where(Message.status == "queued", Message.channel == "gsm")  # soft-deleted rows excluded
        .order_by(Message.created_at, Message.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if message is None:
        return None
    message.status = "sending"
    message.gsm_device_id = device_id
    db.add(
        MessageLease(
            message_id=message.id,
            worker_id=worker.id,
            device_id=device_id,
            expires_at=utcnow() + timedelta(seconds=settings.worker_lease_seconds),
        )
    )
    db.flush()
    return message


def held_lease(db: Session, worker: WorkerAccount, message_id: int) -> MessageLease | None:
    lease = db.scalars(
        select(MessageLease).where(MessageLease.message_id == message_id).with_for_update()
    ).one_or_none()
    return lease if lease and lease.worker_id == worker.id else None


def finish(db: Session, lease: MessageLease, status: str, error: str | None) -> None:
    """Record the outcome and release the lease. A core UPDATE, so it also reaches a message that
    was soft-deleted while it was being sent. The caller commits."""
    values: dict = {
        "status": status,
        "error_message": error[:MAX_ERROR_LENGTH] if error else None,
    }
    if status == "sent":
        values["sent_at"] = utcnow()
    db.execute(update(Message).where(Message.id == lease.message_id).values(**values))
    db.delete(lease)
    db.flush()
