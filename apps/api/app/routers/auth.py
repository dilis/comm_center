import logging
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import login_limits, push, security, sessions
from app.audit import client_ip, record_activity, record_login
from app.authz import AuthUser
from app.clock import utcnow
from app.config import settings
from app.contact_ops import replace_phones as replace_contact_phones
from app.db import get_db
from app.deps import (
    can_log_in,
    get_current_user,
    get_current_user_row,
    get_session_id,
    unauthorized,
)
from app.models import Contact, ContactPhone, PushSubscription, RefreshToken, User
from app.pagination import Page, PageParams, paginate
from app.schemas import PartialNameParts, PhoneIn, PhoneOut

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class MeOut(BaseModel):
    id: int
    username: str
    name: str  # first, middle and last name joined by spaces
    first_name: str
    middle_name: str | None
    last_name: str | None
    email: str | None
    phones: list[PhoneOut]
    groups: list[str]
    permissions: list[str]  # "resource:action"


class ProfileUpdate(PartialNameParts):
    email: EmailStr | None = None
    clear_email: bool = False


class PhonesUpdate(BaseModel):
    phones: list[PhoneIn]


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=security.MIN_PASSWORD_LENGTH, max_length=256)


def _too_many(wait: int) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "too many failed attempts; try again later",
        headers={"Retry-After": str(wait)},
    )


def _user_id_of(db: Session, username: str) -> int | None:
    return db.scalars(select(User.id).where(User.username == username)).one_or_none()


def _issue_tokens(
    db: Session, user_id: int, request: Request, rotating: RefreshToken | None = None
) -> TokenPair:
    """A new pair: a new session, or the continuation of the one ``rotating`` belongs to."""
    session_id = rotating.session_id if rotating else uuid.uuid4().hex
    access, _ = security.create_token(
        user_id, "access", settings.access_token_ttl_seconds, session_id
    )
    refresh, jti = security.create_token(user_id, "refresh", settings.refresh_token_ttl_seconds)
    db.add(
        RefreshToken(
            jti=jti,
            user_id=user_id,
            session_id=session_id,
            # left unset for a new session, so that the database fills it in
            **({"signed_in_at": rotating.signed_in_at} if rotating else {}),
            ip=client_ip(request),
            user_agent=(request.headers.get("user-agent") or "")[:255] or None,
            expires_at=utcnow() + timedelta(seconds=settings.refresh_token_ttl_seconds),
        )
    )
    db.commit()
    return TokenPair(
        access_token=access, refresh_token=refresh, expires_in=settings.access_token_ttl_seconds
    )


def _revoke_all(db: Session, user_id: int) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


@router.post("/login", response_model=TokenPair)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenPair:
    ip = client_ip(request)
    key = login_limits.normalize_username(body.username)
    wait = login_limits.blocked_for(db, login_limits.LOGIN, key, ip)
    if wait:
        log.warning("login blocked for %r from %s: too many failures", body.username[:64], ip)
        record_login(db, request, "login_blocked", body.username, _user_id_of(db, body.username))
        db.commit()
        raise _too_many(wait)
    user = db.scalars(select(User).where(User.username == body.username)).one_or_none()
    # Always verify a hash so the response time does not reveal whether the username exists.
    hash_ = user.password_hash if user and user.password_hash else security.DUMMY_HASH
    valid = security.verify_password(hash_, body.password)
    if not (valid and can_log_in(user)):
        record_login(db, request, "login_failed", body.username, user.id if user else None)
        login_limits.record_failure(db, login_limits.LOGIN, key, ip)
        log.warning("failed login for %r from %s", body.username[:64], ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    record_login(db, request, "login", user.username, user.id)
    login_limits.forget_failures(db, login_limits.LOGIN, key)  # commits the log row too
    return _issue_tokens(db, user.id, request)


@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshRequest, request: Request, db: Session = Depends(get_db)) -> TokenPair:
    """Rotate: the presented refresh token is spent and a new pair is issued. Invalid or replayed
    tokens count against the caller's address (a valid refresh never does)."""
    ip = client_ip(request)
    wait = login_limits.blocked_for(db, login_limits.REFRESH, "", ip)
    if wait:
        log.warning("refresh blocked for %s: too many invalid tokens", ip)
        raise _too_many(wait)
    try:
        return _rotate(db, body.refresh_token, request)
    except HTTPException:
        login_limits.record_failure(db, login_limits.REFRESH, "", ip)
        raise


def _rotate(db: Session, refresh_token: str, request: Request) -> TokenPair:
    try:
        claims = security.decode_token(refresh_token, "refresh")
    except security.TokenError:
        raise unauthorized() from None
    stored = db.scalars(
        select(RefreshToken).where(RefreshToken.jti == claims["jti"]).with_for_update()
    ).one_or_none()
    if stored is None or stored.user_id != int(claims["sub"]):
        raise unauthorized()
    if stored.revoked_at is not None:
        # A spent token came back: assume it leaked and end every session of this user.
        _revoke_all(db, stored.user_id)
        owner = db.scalars(select(User.username).where(User.id == stored.user_id)).one_or_none()
        record_login(db, request, "sessions_revoked", owner or "", stored.user_id)
        db.commit()
        raise unauthorized()
    user = db.scalars(select(User).where(User.id == stored.user_id)).one_or_none()
    if not can_log_in(user):
        raise unauthorized()
    stored.revoked_at = utcnow()
    return _issue_tokens(db, user.id, request, rotating=stored)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(body: RefreshRequest, request: Request, db: Session = Depends(get_db)) -> Response:
    """Revoke the refresh token. Idempotent; the short-lived access token simply expires."""
    try:
        claims = security.decode_token(body.refresh_token, "refresh")
    except security.TokenError:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    revoked = db.execute(
        update(RefreshToken)
        .where(RefreshToken.jti == claims["jti"], RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    if revoked.rowcount:  # a repeated logout is not a second sign-out
        owner = db.scalars(select(User).where(User.id == int(claims["sub"]))).one_or_none()
        if owner:
            record_login(db, request, "logout", owner.username, owner.id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _me(db: Session, user: User, auth: AuthUser) -> MeOut:
    from app.models import AccessGroup, UserGroup

    contact = db.get(Contact, user.contact_id)
    phones = db.scalars(
        select(ContactPhone)
        .where(ContactPhone.contact_id == user.contact_id)
        .order_by(ContactPhone.id)
    )
    groups = db.scalars(
        select(AccessGroup.name)
        .join(UserGroup, UserGroup.group_id == AccessGroup.id)
        .where(UserGroup.user_id == user.id)
        .order_by(AccessGroup.name)
    )
    return MeOut(
        id=user.id,
        username=user.username,
        name=contact.name,
        first_name=contact.first_name,
        middle_name=contact.middle_name,
        last_name=contact.last_name,
        email=contact.email,
        phones=[
            PhoneOut(phone=p.phone_e164, label=p.label, is_primary=p.is_primary) for p in phones
        ],
        groups=list(groups),
        permissions=sorted(f"{r}:{a}" for r, a in auth.permissions),
    )


@router.get("/me", response_model=MeOut)
def read_me(
    user: User = Depends(get_current_user_row),
    auth: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MeOut:
    return _me(db, user, auth)


class MySessionOut(sessions.SessionOut):
    current: bool  # the session making this request


@router.get("/me/sessions", response_model=Page[MySessionOut])
def my_sessions(
    params: PageParams = Depends(),
    user: User = Depends(get_current_user_row),
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
) -> Page[MySessionOut]:
    """Where the caller is signed in, most recently active first."""
    stmt = sessions.live_tokens().where(RefreshToken.user_id == user.id)
    tokens, total = paginate(db, stmt, params, *sessions.ORDER)
    items = [
        MySessionOut(**sessions.session_fields(t), current=t.session_id == session_id)
        for t in tokens
    ]
    return Page(items=items, total=total, page=params.page, page_size=params.page_size)


@router.patch("/me/profile", response_model=MeOut)
def update_profile(
    body: ProfileUpdate,
    request: Request,
    user: User = Depends(get_current_user_row),
    auth: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MeOut:
    """Self-service: edits the caller's own contact, bypassing resource scoping."""
    contact = db.get(Contact, user.contact_id)
    body.apply_name(contact)
    if body.clear_email:
        contact.email = None
    elif body.email is not None:
        contact.email = body.email
    record_activity(db, request, user.id, "update", "profile", user.id, "Updated own profile")
    db.commit()
    return _me(db, user, auth)


@router.put("/me/phones", response_model=MeOut)
def replace_phones(
    body: PhonesUpdate,
    request: Request,
    user: User = Depends(get_current_user_row),
    auth: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MeOut:
    """Replace the caller's phone list: absent numbers are soft-deleted, new ones added."""
    replace_contact_phones(db, user.contact_id, body.phones)
    record_activity(db, request, user.id, "update", "phones", user.id, "Updated own phone numbers")
    db.commit()
    return _me(db, user, auth)


@router.put("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: PasswordChange,
    request: Request,
    user: User = Depends(get_current_user_row),
    db: Session = Depends(get_db),
) -> Response:
    key, ip = str(user.id), client_ip(request)
    wait = login_limits.blocked_for(db, login_limits.PASSWORD, key, ip)
    if wait:
        log.warning("password change blocked for user %s: too many wrong passwords", user.id)
        raise _too_many(wait)
    if not security.verify_password(user.password_hash, body.current_password):
        login_limits.record_failure(db, login_limits.PASSWORD, key, ip)
        log.warning("wrong current password for user %s from %s", user.id, ip)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "current password is incorrect")
    login_limits.forget_failures(db, login_limits.PASSWORD, key)
    user.password_hash = security.hash_password(body.new_password)
    _revoke_all(db, user.id)  # other sessions must log in again
    record_activity(db, request, user.id, "change_password", "account", user.id, "Changed own password")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class PushConfigOut(BaseModel):
    enabled: bool
    public_key: str | None  # what the browser subscribes with; none when push is not set up


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=255)
    auth: str = Field(min_length=1, max_length=255)


def _https_endpoint(value: str) -> str:
    if not value.startswith("https://") or " " in value or len(value) > 2048:
        raise ValueError("endpoint must be an https URL")
    return value


class PushSubscribe(BaseModel):
    endpoint: str
    keys: PushKeys

    @field_validator("endpoint")
    @classmethod
    def _check(cls, value: str) -> str:
        return _https_endpoint(value)


class PushUnsubscribe(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2048)


@router.get("/me/push", response_model=PushConfigOut)
def push_config(_: AuthUser = Depends(get_current_user)) -> PushConfigOut:
    """Whether notifications are set up, and the public key a browser needs to subscribe."""
    enabled = push.push_enabled()
    return PushConfigOut(enabled=enabled, public_key=settings.vapid_public_key if enabled else None)


@router.put("/me/push", status_code=status.HTTP_204_NO_CONTENT)
def push_subscribe(
    body: PushSubscribe,
    request: Request,
    user: User = Depends(get_current_user_row),
    db: Session = Depends(get_db),
) -> Response:
    """Allow this browser to notify the caller. Idempotent; a browser that was subscribed as someone
    else moves to the caller (one browser, one endpoint)."""
    if not push.push_enabled():
        raise HTTPException(status.HTTP_409_CONFLICT, "push notifications are not set up")
    digest = push.endpoint_hash(body.endpoint)
    row = db.scalars(
        select(PushSubscription).where(PushSubscription.endpoint_hash == digest)
    ).one_or_none()
    if row is None:
        row = PushSubscription(endpoint=body.endpoint, endpoint_hash=digest)
        db.add(row)
    row.user_id = user.id
    row.p256dh, row.auth = body.keys.p256dh, body.keys.auth
    row.user_agent = (request.headers.get("user-agent") or "")[:255] or None
    record_activity(db, request, user.id, "subscribe", "push", user.id, "Turned on notifications")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/me/push", status_code=status.HTTP_204_NO_CONTENT)
def push_unsubscribe(
    body: PushUnsubscribe,
    request: Request,
    user: User = Depends(get_current_user_row),
    db: Session = Depends(get_db),
) -> Response:
    """Stop notifying this browser. Only the caller's own subscription; an unknown one is ignored."""
    row = db.scalars(
        select(PushSubscription).where(
            PushSubscription.endpoint_hash == push.endpoint_hash(body.endpoint),
            PushSubscription.user_id == user.id,
        )
    ).one_or_none()
    if row is not None:
        db.delete(row)
        record_activity(db, request, user.id, "unsubscribe", "push", user.id, "Turned off notifications")
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
