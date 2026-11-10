import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field, model_validator
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import login_limits, security
from app.audit import record_activity
from app.authz import AuthUser, check_assignable_groups, forbidden, require, scope
from app.clock import utcnow
from app.contact_ops import phones_by_contact, replace_phones
from app.db import get_db
from app.deps import get_current_user
from app.models import AccessGroup, Contact, RefreshToken, User, UserGroup
from app.pagination import Page, PageParams, paginate
from app.schemas import ContactIn, PartialNameParts, PhoneIn, PhoneOut, SortOrder

log = logging.getLogger(__name__)
router = APIRouter(prefix="/users", tags=["users"])


class GroupRef(BaseModel):
    id: int
    name: str


class UserOut(BaseModel):
    id: int
    username: str
    contact_id: int
    name: str  # first, middle and last name joined by spaces
    first_name: str
    middle_name: str | None
    last_name: str | None
    email: str | None
    phones: list[PhoneOut]
    is_active: bool
    owner_id: int
    groups: list[GroupRef]
    locked: bool  # too many failed sign-ins; an administrator can unlock (POST /users/{id}/unlock)
    created_at: datetime


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=security.MIN_PASSWORD_LENGTH, max_length=256)
    contact_id: int | None = None  # link an existing contact...
    contact: ContactIn | None = None  # ...or create one (exactly one of the two)
    is_active: bool = True
    group_ids: list[int] = []

    @model_validator(mode="after")
    def _one_contact_source(self):
        if (self.contact_id is None) == (self.contact is None):
            raise ValueError("give exactly one of contact_id and contact")
        return self


class UserUpdate(PartialNameParts):
    """Omitted fields stay as they are; an explicit ``email: null`` clears the email.

    ``username``, ``is_active`` and ``group_ids`` are checked against ``users`` permissions;
    ``first_name``, ``middle_name``, ``last_name``, ``email`` and ``phones`` live on the contact and need ``contacts`` update.
    """

    username: str | None = Field(default=None, min_length=1, max_length=64)
    is_active: bool | None = None
    group_ids: list[int] | None = None
    email: EmailStr | None = None
    phones: list[PhoneIn] | None = None


def to_out(db: Session, users: list[User]) -> list[UserOut]:
    ids = [u.id for u in users]
    contacts = (
        {
            c.id: c
            for c in db.scalars(
                select(Contact).where(Contact.id.in_([u.contact_id for u in users]))
            )
        }
        if users
        else {}
    )
    phones = phones_by_contact(db, contacts)
    groups: dict[int, list[GroupRef]] = {}
    if ids:
        rows = db.execute(
            select(UserGroup.user_id, AccessGroup.id, AccessGroup.name)
            .join(AccessGroup, AccessGroup.id == UserGroup.group_id)
            .where(UserGroup.user_id.in_(ids))
            .order_by(AccessGroup.name)
        )
        for user_id, gid, name in rows:
            groups.setdefault(user_id, []).append(GroupRef(id=gid, name=name))
    locked = login_limits.locked_usernames(db, [u.username for u in users])
    return [
        UserOut(
            id=u.id,
            username=u.username,
            contact_id=u.contact_id,
            name=contacts[u.contact_id].name,
            first_name=contacts[u.contact_id].first_name,
            middle_name=contacts[u.contact_id].middle_name,
            last_name=contacts[u.contact_id].last_name,
            email=contacts[u.contact_id].email,
            phones=phones.get(u.contact_id, []),
            is_active=u.is_active,
            owner_id=u.owner_id,
            groups=groups.get(u.id, []),
            locked=u.username in locked,
            created_at=u.created_at,
        )
        for u in users
    ]


def humans(stmt):
    """System agents are hidden from the users API."""
    return stmt.where(User.is_system.is_(False))


def get_scoped(db: Session, caller: AuthUser, user_id: int) -> User:
    stmt = scope(humans(select(User).where(User.id == user_id)), caller, "users")
    user = db.scalars(stmt).one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    return user


def set_groups(db: Session, user_id: int, group_ids: list[int]) -> None:
    db.execute(delete(UserGroup).where(UserGroup.user_id == user_id))
    db.add_all(UserGroup(user_id=user_id, group_id=g) for g in set(group_ids))


def conflict(exc: IntegrityError) -> HTTPException:
    text = str(exc)
    if "uq_users_active_username" in text:
        return HTTPException(status.HTTP_409_CONFLICT, "username already in use")
    if "uq_users_contact_id" in text:
        return HTTPException(status.HTTP_409_CONFLICT, "contact already belongs to a user")
    raise exc


SORTS = {"username": User.username, "created_at": User.created_at}


@router.get("", response_model=Page[UserOut])
def list_users(
    q: str | None = None,
    is_active: bool | None = None,
    sort: Literal["username", "created_at"] = "username",
    order: SortOrder = "asc",
    params: PageParams = Depends(),
    caller: AuthUser = Depends(get_current_user),  # scope() answers 403 without read access
    db: Session = Depends(get_db),
) -> Page[UserOut]:
    stmt = scope(humans(select(User)), caller, "users")
    if is_active is not None:
        stmt = stmt.where(User.is_active.is_(is_active))
    if q:
        stmt = stmt.join(Contact, Contact.id == User.contact_id).where(
            User.username.contains(q, autoescape=True) | Contact.name.contains(q, autoescape=True)
        )
    column = SORTS[sort]
    users, total = paginate(
        db, stmt, params, column.desc() if order == "desc" else column.asc(), User.id
    )
    return Page(items=to_out(db, users), total=total, page=params.page, page_size=params.page_size)


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate,
    request: Request,
    caller: AuthUser = Depends(require("users", "create")),
    db: Session = Depends(get_db),
) -> UserOut:
    check_assignable_groups(db, caller, body.group_ids)
    if body.contact is not None:
        if not caller.can("contacts", "create"):
            raise forbidden()
        contact = Contact(
            first_name=body.contact.first_name,
            middle_name=body.contact.middle_name,
            last_name=body.contact.last_name,
            type="person",
            email=body.contact.email,
            notes=body.contact.notes,
            owner_id=caller.id,
        )
        db.add(contact)
        db.flush()
        replace_phones(db, contact.id, body.contact.phones)
        contact_id = contact.id
    else:
        # Linking needs read access to that contact, same as any other use of it.
        found = db.scalars(
            scope(select(Contact).where(Contact.id == body.contact_id), caller, "contacts")
        ).one_or_none()
        if found is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "contact not found")
        contact_id = found.id
    user = User(
        contact_id=contact_id,
        username=body.username,
        password_hash=security.hash_password(body.password),
        is_active=body.is_active,
        owner_id=caller.id,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()  # also discards a contact created above
        raise conflict(exc) from None
    set_groups(db, user.id, body.group_ids)
    record_activity(db, request, caller.id, "create", "user", user.id, f"Created user {user.username}")
    db.commit()
    return to_out(db, [user])[0]


@router.get("/{user_id}", response_model=UserOut)
def read_user(
    user_id: int, caller: AuthUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> UserOut:
    return to_out(db, [get_scoped(db, caller, user_id)])[0]


@router.put("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    body: UserUpdate,
    request: Request,
    caller: AuthUser = Depends(require("users", "update")),
    db: Session = Depends(get_db),
) -> UserOut:
    user = get_scoped(db, caller, user_id)
    fields = body.model_fields_set
    if user.id == caller.id and body.is_active is False:
        raise HTTPException(status.HTTP_409_CONFLICT, "you cannot deactivate yourself")

    if fields & {"first_name", "middle_name", "last_name", "email", "phones"}:
        # These live on the contact, so they need contacts:update on that contact.
        if not caller.can("contacts", "update"):
            raise forbidden()
        contact = db.scalars(
            scope(select(Contact).where(Contact.id == user.contact_id), caller, "contacts")
        ).one_or_none()
        if contact is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "contact not found")
        body.apply_name(contact)
        if "email" in fields:
            contact.email = body.email
        if body.phones is not None:
            replace_phones(db, contact.id, body.phones)
    if body.group_ids is not None:
        check_assignable_groups(db, caller, body.group_ids)
        set_groups(db, user.id, body.group_ids)
    if body.username is not None:
        user.username = body.username
    if body.is_active is not None:
        user.is_active = body.is_active
    changed = ", ".join(sorted(fields))
    record_activity(db, request, caller.id, "update", "user", user.id, f"Updated user {user.username} ({changed})")
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise conflict(exc) from None
    return to_out(db, [user])[0]


@router.post("/{user_id}/unlock", status_code=status.HTTP_204_NO_CONTENT)
def unlock_user(
    user_id: int,
    request: Request,
    caller: AuthUser = Depends(require("users", "update")),
    db: Session = Depends(get_db),
) -> Response:
    """Clear the failed sign-ins (and wrong-password guesses) that lock this user out. Harmless
    for a user who is not locked."""
    user = get_scoped(db, caller, user_id)
    login_limits.unlock_user(db, user.username, user.id)
    record_activity(db, request, caller.id, "unlock", "user", user.id, f"Unlocked user {user.username}")
    db.commit()
    log.info("user %s unlocked by user %s", user.id, caller.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    request: Request,
    caller: AuthUser = Depends(require("users", "delete")),
    db: Session = Depends(get_db),
) -> Response:
    user = get_scoped(db, caller, user_id)
    if user.id == caller.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "you cannot delete yourself")
    now = utcnow()
    user.deleted_at = now  # the contact stays; owned resources are not cascaded
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    record_activity(db, request, caller.id, "delete", "user", user.id, f"Deleted user {user.username}")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
