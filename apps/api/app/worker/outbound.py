"""Outbound: claim queued messages from MySQL (the queue) and send them through the provider."""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.clock import utcnow
from app.models import GsmDevice, Message
from app.worker.provider import ChannelProvider, PermanentSendError, ProviderError

log = logging.getLogger(__name__)
MAX_ERROR_LENGTH = 1000
MAX_DEVICE_ERROR_LENGTH = 500  # the width of gsm_device.last_error


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    backoff_base: float = 2.0  # seconds before the 2nd attempt; doubles each time

    def delay(self, attempt: int) -> float:
        """Wait after failed attempt number ``attempt`` (1-based)."""
        return self.backoff_base * 2 ** (attempt - 1)


@dataclass(frozen=True)
class Claimed:
    id: int
    phone_number: str
    content: str


def claim_next(db: Session, device_id: int, *, commit: bool = True) -> Claimed | None:
    """Take the oldest queued message that no other worker holds (``FOR UPDATE SKIP LOCKED``) and
    mark it ``sending`` on this device. With ``commit=False`` the row stays locked to the caller."""
    message = db.scalars(
        select(Message)
        .where(Message.status == "queued", Message.channel == "gsm")  # soft-deleted rows excluded
        .order_by(Message.created_at, Message.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if message is None:
        db.rollback()
        return None
    message.status = "sending"
    message.gsm_device_id = device_id
    claimed = Claimed(message.id, message.phone_number, message.content)
    if commit:
        db.commit()
    return claimed


def _finish(
    session_factory: sessionmaker, message_id: int, status: str, error: str | None = None
) -> None:
    # A core UPDATE: it also reaches a message that was soft-deleted while it was being sent.
    values = {"status": status, "error_message": error[:MAX_ERROR_LENGTH] if error else None}
    if status == "sent":
        values["sent_at"] = utcnow()
    with session_factory() as db:
        db.execute(update(Message).where(Message.id == message_id).values(**values))
        db.commit()


def record_device_error(session_factory: sessionmaker, device_id: int, error: str) -> None:
    """Keep the latest modem problem on the device so it shows up in ``GET /devices``."""
    try:
        with session_factory() as db:
            db.execute(
                update(GsmDevice)
                .where(GsmDevice.id == device_id)
                .values(last_error=error[:MAX_DEVICE_ERROR_LENGTH], last_error_at=utcnow())
            )
            db.commit()
    except Exception:  # health reporting must never stop the worker
        log.exception("device %s: could not record the modem error", device_id)


def send_one(
    session_factory: sessionmaker,
    provider: ChannelProvider,
    device_id: int,
    policy: RetryPolicy,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Claim and send one message. Returns False when the queue is empty."""
    with session_factory() as db:
        claimed = claim_next(db, device_id)
    if claimed is None:
        return False
    try:
        for attempt in range(1, policy.max_attempts + 1):
            try:
                provider.send(claimed.phone_number, claimed.content)
            except PermanentSendError as exc:
                _finish(session_factory, claimed.id, "failed", str(exc))
                log.warning("message %s rejected: %s", claimed.id, exc)
                return True
            except ProviderError as exc:
                if attempt == policy.max_attempts:
                    _finish(session_factory, claimed.id, "failed", str(exc))
                    record_device_error(session_factory, device_id, str(exc))
                    log.warning("message %s failed after %s attempts: %s", claimed.id, attempt, exc)
                    return True
                log.info("message %s attempt %s failed (%s); retrying", claimed.id, attempt, exc)
                sleep(policy.delay(attempt))
            else:
                _finish(session_factory, claimed.id, "sent")
                return True
    except Exception as exc:  # never leave a claimed message stuck in 'sending'
        log.exception("unexpected error sending message %s", claimed.id)
        _finish(session_factory, claimed.id, "failed", f"unexpected error: {exc}")
    return True


def recover_interrupted(db: Session, device_id: int) -> int:
    """Messages this device left ``sending`` when the worker died may or may not have gone out.
    Re-sending risks a duplicate SMS, so they are failed for a person to decide."""
    result = db.execute(
        update(Message)
        .where(Message.status == "sending", Message.gsm_device_id == device_id)
        .values(status="failed", error_message="worker stopped while sending; delivery unknown")
    )
    db.commit()
    return result.rowcount
