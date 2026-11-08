"""Rate limiting of sign-in style endpoints, kept in the database so every API process shares one
count.

Only failed attempts are recorded, under a kind (what was attempted), a key (who it was aimed at)
and the client address. Once a key or an address has too many failures of one kind inside the
window (``LOGIN_LOCKOUT_SECONDS``), that endpoint answers 429 until the oldest of them ages out.
Attempts made while blocked are not recorded, so hammering a locked account does not extend the
lock. Success clears the key's failures.

- ``LOGIN``: keyed by the normalized username, whether or not it exists, so a lockout reveals
  nothing about which usernames are real.
- ``PASSWORD``: someone signed in guessing the current password in ``PUT /auth/me/password``;
  keyed by user id.
- ``REFRESH``: invalid or replayed refresh tokens; by address only (a valid refresh is never
  counted).
"""

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.config import settings
from app.models import LoginAttempt

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Policy:
    kind: str
    per_key: Callable[[], int] | None  # failures allowed per key; None: not limited by key
    per_ip: Callable[[], int] | None  # failures allowed per address; None: not limited by address


LOGIN = Policy("login", lambda: settings.login_max_failures, lambda: settings.login_max_failures_per_ip)
PASSWORD = Policy("password", lambda: settings.password_max_failures, None)
REFRESH = Policy("refresh", None, lambda: settings.refresh_max_failures_per_ip)


def normalize_username(username: str) -> str:
    return username.strip().casefold()[:255]


def _window_start():
    return utcnow() - timedelta(seconds=settings.login_lockout_seconds)


def _retry_after(db: Session, kind: str, column, value: str, limit: int) -> int:
    """Seconds until a new attempt is allowed for this key; 0 if it is not blocked."""
    times = db.scalars(
        select(LoginAttempt.created_at)
        .where(LoginAttempt.kind == kind, column == value, LoginAttempt.created_at > _window_start())
        .order_by(LoginAttempt.created_at.desc())
        .limit(limit)
    ).all()
    if len(times) < limit:
        return 0
    # The block lifts when the failure that makes the count reach the limit leaves the window.
    unblock_at = times[-1] + timedelta(seconds=settings.login_lockout_seconds)
    remaining = math.ceil((unblock_at - utcnow()).total_seconds())
    return min(max(1, remaining), settings.login_lockout_seconds)


def blocked_for(db: Session, policy: Policy, key: str, ip: str) -> int:
    """Seconds the caller must wait, or 0 when this attempt may go ahead."""
    waits = [0]
    if policy.per_key:
        waits.append(_retry_after(db, policy.kind, LoginAttempt.username, key, policy.per_key()))
    if policy.per_ip:
        waits.append(_retry_after(db, policy.kind, LoginAttempt.ip, ip, policy.per_ip()))
    return max(waits)


def record_failure(db: Session, policy: Policy, key: str, ip: str) -> None:
    now = utcnow()
    db.add(LoginAttempt(kind=policy.kind, username=key, ip=ip, created_at=now))
    # Housekeeping: nothing older than the window can count any more.
    db.execute(delete(LoginAttempt).where(LoginAttempt.created_at < _window_start()))
    db.commit()


def forget_failures(db: Session, policy: Policy, key: str) -> None:
    db.execute(
        delete(LoginAttempt).where(LoginAttempt.kind == policy.kind, LoginAttempt.username == key)
    )
    db.commit()


def unlock_user(db: Session, username: str, user_id: int) -> None:
    """An administrator clears a person's sign-in and password-guessing lockouts."""
    forget_failures(db, LOGIN, normalize_username(username))
    forget_failures(db, PASSWORD, str(user_id))


def locked_usernames(db: Session, usernames: list[str]) -> set[str]:
    """Which of these usernames are currently locked out of signing in (any kind of lock)."""
    if not usernames:
        return set()
    keys = {normalize_username(u): u for u in usernames}
    counts = dict(
        db.execute(
            select(LoginAttempt.username, func.count())
            .where(
                LoginAttempt.kind == "login",
                LoginAttempt.username.in_(keys),
                LoginAttempt.created_at > _window_start(),
            )
            .group_by(LoginAttempt.username)
        ).all()
    )
    return {keys[k] for k, n in counts.items() if n >= settings.login_max_failures}
