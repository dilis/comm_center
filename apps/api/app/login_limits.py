"""Login rate limiting, kept in the database so every API process shares one count.

Only failed attempts are recorded, under the normalized username (whether or not it exists, so a
lockout reveals nothing) and the client address. Once a username or an address has too many
failures inside the window, sign-in answers 429 until the oldest of them ages out. Attempts made
while blocked are not recorded, so hammering a locked account does not extend the lock.
"""

import logging
import math
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.config import settings
from app.models import LoginAttempt

log = logging.getLogger(__name__)


def normalize_username(username: str) -> str:
    return username.strip().casefold()[:255]


def _retry_after(db: Session, column, value: str, limit: int) -> int:
    """Seconds until a new attempt is allowed for this key; 0 if it is not blocked."""
    window_start = utcnow() - timedelta(seconds=settings.login_lockout_seconds)
    times = db.scalars(
        select(LoginAttempt.created_at)
        .where(column == value, LoginAttempt.created_at > window_start)
        .order_by(LoginAttempt.created_at.desc())
        .limit(limit)
    ).all()
    if len(times) < limit:
        return 0
    # The block lifts when the failure that makes the count reach the limit leaves the window.
    unblock_at = times[-1] + timedelta(seconds=settings.login_lockout_seconds)
    remaining = math.ceil((unblock_at - utcnow()).total_seconds())
    return min(max(1, remaining), settings.login_lockout_seconds)


def blocked_for(db: Session, username: str, ip: str) -> int:
    """Seconds the caller must wait, or 0 when this attempt may go ahead."""
    return max(
        _retry_after(db, LoginAttempt.username, normalize_username(username), settings.login_max_failures),
        _retry_after(db, LoginAttempt.ip, ip, settings.login_max_failures_per_ip),
    )


def record_failure(db: Session, username: str, ip: str) -> None:
    now = utcnow()
    db.add(LoginAttempt(username=normalize_username(username), ip=ip, created_at=now))
    # Housekeeping: nothing older than the window can count any more.
    db.execute(
        delete(LoginAttempt).where(
            LoginAttempt.created_at < now - timedelta(seconds=settings.login_lockout_seconds)
        )
    )
    db.commit()


def forget_failures(db: Session, username: str) -> None:
    db.execute(delete(LoginAttempt).where(LoginAttempt.username == normalize_username(username)))
    db.commit()
