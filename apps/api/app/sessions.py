"""Signed-in sessions. A session is one sign-in; rotation replaces its refresh token but keeps
``session_id``, so at any moment a live session has exactly one token that is neither revoked nor
expired. "Signed in" therefore means "can still get an access token", not "has the app open"."""

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import Select, delete, select, update
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.models import PushSubscription, RefreshToken

# Newest activity first.
ORDER = (RefreshToken.created_at.desc(), RefreshToken.id.desc())


class SessionOut(BaseModel):
    id: str
    ip: str | None  # not known for a sign-in made before this was recorded
    user_agent: str | None
    signed_in_at: datetime
    last_active_at: datetime  # when the session last signed in or refreshed


def live_tokens() -> Select:
    """The current token of every live session."""
    return select(RefreshToken).where(
        RefreshToken.revoked_at.is_(None), RefreshToken.expires_at > utcnow()
    )


def is_live(db: Session, session_id: str) -> bool:
    stmt = live_tokens().where(RefreshToken.session_id == session_id)
    return db.scalars(stmt.limit(1)).first() is not None


def end(db: Session, user_id: int, session_id: str) -> bool:
    """Sign one of the user's sessions out: it cannot refresh any more and its browser is not
    notified. False if the user has no such live session. The caller commits. An access token the
    session already holds works until it expires."""
    revoked = db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == user_id,
            RefreshToken.session_id == session_id,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > utcnow(),
        )
        .values(revoked_at=utcnow())
    )
    if not revoked.rowcount:
        return False
    db.execute(
        delete(PushSubscription).where(
            PushSubscription.user_id == user_id, PushSubscription.session_id == session_id
        )
    )
    return True


def session_fields(token: RefreshToken) -> dict:
    return {
        "id": token.session_id,
        "ip": token.ip,
        "user_agent": token.user_agent,
        "signed_in_at": token.signed_in_at,
        "last_active_at": token.created_at,
    }
