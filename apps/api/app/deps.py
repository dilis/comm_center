from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import security
from app.authz import AuthUser, effective_permissions
from app.db import get_db
from app.models import GsmDevice, User

_bearer = HTTPBearer(auto_error=False)


def unauthorized() -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, "not authenticated", headers={"WWW-Authenticate": "Bearer"}
    )


def can_log_in(user: User | None) -> bool:
    return bool(
        user and user.is_active and user.login_enabled and not user.is_system and user.password_hash
    )


def get_current_user_row(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise unauthorized()
    try:
        claims = security.decode_token(credentials.credentials, "access")
    except security.TokenError:
        raise unauthorized() from None
    user = db.scalars(select(User).where(User.id == int(claims["sub"]))).one_or_none()
    if not can_log_in(user):
        raise unauthorized()
    return user


def get_current_user(
    user: User = Depends(get_current_user_row), db: Session = Depends(get_db)
) -> AuthUser:
    """The caller with permissions loaded fresh from the database on every request."""
    return AuthUser(id=user.id, permissions=effective_permissions(db, user.id))


def get_current_worker(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> GsmDevice:
    """The device behind a worker token (the worker signed in as the device's agent). User tokens
    (and the other way round) are refused because the two kinds differ in their ``typ`` claim."""
    if credentials is None:
        raise unauthorized()
    try:
        claims = security.decode_token(credentials.credentials, "worker")
    except security.TokenError:
        raise unauthorized() from None
    device = db.scalars(
        select(GsmDevice).where(GsmDevice.agent_user_id == int(claims["sub"]))
    ).one_or_none()
    agent = db.get(User, device.agent_user_id) if device else None
    if device is None or agent is None or not agent.is_active:
        raise unauthorized()
    return device
