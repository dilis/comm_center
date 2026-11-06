from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import security
from app.authz import AuthUser
from app.config import settings
from app.db import get_db
from app.deps import can_log_in, get_current_user, get_current_user_row, unauthorized
from app.models import Contact, ContactPhone, RefreshToken, User
from app.phones import normalize_e164

router = APIRouter(prefix="/auth", tags=["auth"])


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)  # the database stores naive UTC


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


class PhoneIn(BaseModel):
    phone: str
    label: str | None = Field(default=None, max_length=32)
    is_primary: bool = False

    @field_validator("phone")
    @classmethod
    def _normalize(cls, value: str) -> str:
        try:
            return normalize_e164(value)
        except ValueError as exc:
            raise ValueError(str(exc)) from None


class PhoneOut(BaseModel):
    phone: str
    label: str | None
    is_primary: bool


class MeOut(BaseModel):
    id: int
    username: str
    name: str
    email: str | None
    phones: list[PhoneOut]
    groups: list[str]
    permissions: list[str]  # "resource:action"


class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    email: EmailStr | None = None
    clear_email: bool = False


class PhonesUpdate(BaseModel):
    phones: list[PhoneIn]


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=security.MIN_PASSWORD_LENGTH, max_length=256)


def _issue_tokens(db: Session, user_id: int) -> TokenPair:
    access, _ = security.create_token(user_id, "access", settings.access_token_ttl_seconds)
    refresh, jti = security.create_token(user_id, "refresh", settings.refresh_token_ttl_seconds)
    db.add(
        RefreshToken(
            jti=jti,
            user_id=user_id,
            expires_at=_now() + timedelta(seconds=settings.refresh_token_ttl_seconds),
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
        .values(revoked_at=_now())
    )


@router.post("/login", response_model=TokenPair)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenPair:
    user = db.scalars(select(User).where(User.username == body.username)).one_or_none()
    # Always verify a hash so the response time does not reveal whether the username exists.
    hash_ = user.password_hash if user and user.password_hash else security.DUMMY_HASH
    valid = security.verify_password(hash_, body.password)
    if not (valid and can_log_in(user)):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    return _issue_tokens(db, user.id)


@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshRequest, db: Session = Depends(get_db)) -> TokenPair:
    """Rotate: the presented refresh token is spent and a new pair is issued."""
    try:
        claims = security.decode_token(body.refresh_token, "refresh")
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
        db.commit()
        raise unauthorized()
    user = db.scalars(select(User).where(User.id == stored.user_id)).one_or_none()
    if not can_log_in(user):
        raise unauthorized()
    stored.revoked_at = _now()
    return _issue_tokens(db, user.id)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(body: RefreshRequest, db: Session = Depends(get_db)) -> Response:
    """Revoke the refresh token. Idempotent; the short-lived access token simply expires."""
    try:
        claims = security.decode_token(body.refresh_token, "refresh")
    except security.TokenError:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.jti == claims["jti"], RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _me(db: Session, user: User, auth: AuthUser) -> MeOut:
    from app.models import AccessGroup, UserGroup

    contact = db.get(Contact, user.contact_id)
    phones = db.scalars(
        select(ContactPhone).where(ContactPhone.contact_id == user.contact_id).order_by(ContactPhone.id)
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
        email=contact.email,
        phones=[PhoneOut(phone=p.phone_e164, label=p.label, is_primary=p.is_primary) for p in phones],
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


@router.patch("/me/profile", response_model=MeOut)
def update_profile(
    body: ProfileUpdate,
    user: User = Depends(get_current_user_row),
    auth: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MeOut:
    """Self-service: edits the caller's own contact, bypassing resource scoping."""
    contact = db.get(Contact, user.contact_id)
    if body.name is not None:
        contact.name = body.name
    if body.clear_email:
        contact.email = None
    elif body.email is not None:
        contact.email = body.email
    db.commit()
    return _me(db, user, auth)


@router.put("/me/phones", response_model=MeOut)
def replace_phones(
    body: PhonesUpdate,
    user: User = Depends(get_current_user_row),
    auth: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MeOut:
    """Replace the caller's phone list: absent numbers are soft-deleted, new ones added."""
    numbers = [p.phone for p in body.phones]
    if len(set(numbers)) != len(numbers):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "duplicate phone number")
    if sum(p.is_primary for p in body.phones) > 1:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "only one primary phone")

    existing = {
        p.phone_e164: p
        for p in db.scalars(select(ContactPhone).where(ContactPhone.contact_id == user.contact_id))
    }
    now = _now()
    for number, row in existing.items():
        if number not in numbers:
            row.deleted_at = now
        else:
            row.is_primary = False
    db.flush()  # free the old primary and removed numbers before inserting
    for item in body.phones:
        row = existing.get(item.phone)
        if row is None:
            db.add(
                ContactPhone(
                    contact_id=user.contact_id,
                    phone_e164=item.phone,
                    label=item.label,
                    is_primary=item.is_primary,
                )
            )
        else:
            row.label, row.is_primary = item.label, item.is_primary
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        if "uq_contact_phone_active_phone" in str(exc):
            raise HTTPException(status.HTTP_409_CONFLICT, "phone number already in use") from None
        raise
    return _me(db, user, auth)


@router.put("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: PasswordChange,
    user: User = Depends(get_current_user_row),
    db: Session = Depends(get_db),
) -> Response:
    if not security.verify_password(user.password_hash, body.current_password):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "current password is incorrect")
    user.password_hash = security.hash_password(body.new_password)
    _revoke_all(db, user.id)  # other sessions must log in again
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
