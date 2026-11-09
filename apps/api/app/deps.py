from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import security
from app.authz import AuthUser, effective_permissions
from app.db import get_db
from app.models import User, WorkerAccount

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
) -> WorkerAccount:
    """The worker behind a worker token. User tokens (and the other way round) are refused because
    the two kinds differ in their ``typ`` claim."""
    if credentials is None:
        raise unauthorized()
    try:
        claims = security.decode_token(credentials.credentials, "worker")
    except security.TokenError:
        raise unauthorized() from None
    worker = db.scalars(
        select(WorkerAccount).where(WorkerAccount.id == int(claims["sub"]))
    ).one_or_none()
    if worker is None:
        raise unauthorized()
    return worker
