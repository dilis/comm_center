from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import exists, or_, select, update
from sqlalchemy.orm import Session

from app.authz import AuthUser, require, scope
from app.clock import utcnow
from app.contact_ops import phones_by_contact, replace_phones
from app.db import get_db
from app.deps import get_current_user
from app.models import Contact, ContactPhone, User
from app.pagination import Page, PageParams, paginate
from app.schemas import ContactIn, PhoneIn, PhoneOut, SortOrder

router = APIRouter(prefix="/contacts", tags=["contacts"])


class ContactOut(BaseModel):
    id: int
    name: str
    type: str
    email: str | None
    notes: str | None
    owner_id: int
    user_id: int | None  # the active user this contact belongs to, if any
    phones: list[PhoneOut]
    created_at: datetime
    updated_at: datetime


class ContactUpdate(BaseModel):
    """Full update; ``phones`` omitted leaves the numbers alone. ``owner_id`` is not editable."""

    name: str = Field(min_length=1, max_length=255)
    type: Literal["person", "entity"] = "person"
    email: EmailStr | None = None
    notes: str | None = None
    phones: list[PhoneIn] | None = None


def to_out(db: Session, contacts: list[Contact]) -> list[ContactOut]:
    ids = [c.id for c in contacts]
    phones = phones_by_contact(db, ids)
    user_ids = (
        dict(db.execute(select(User.contact_id, User.id).where(User.contact_id.in_(ids))).all())
        if ids
        else {}
    )
    return [
        ContactOut(
            id=c.id,
            name=c.name,
            type=c.type,
            email=c.email,
            notes=c.notes,
            owner_id=c.owner_id,
            user_id=user_ids.get(c.id),
            phones=phones.get(c.id, []),
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in contacts
    ]


def get_scoped(db: Session, caller: AuthUser, contact_id: int) -> Contact:
    """A contact the caller may read (and so update/delete); 404 otherwise."""
    contact = db.scalars(
        scope(select(Contact).where(Contact.id == contact_id), caller, "contacts")
    ).one_or_none()
    if contact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "contact not found")
    return contact


SORTS = {"name": Contact.name, "created_at": Contact.created_at, "updated_at": Contact.updated_at}


@router.get("", response_model=Page[ContactOut])
def list_contacts(
    q: str | None = None,
    type: Literal["person", "entity"] | None = None,
    sort: Literal["name", "created_at", "updated_at"] = "name",
    order: SortOrder = "asc",
    params: PageParams = Depends(),
    caller: AuthUser = Depends(get_current_user),  # scope() answers 403 without read access
    db: Session = Depends(get_db),
) -> Page[ContactOut]:
    stmt = scope(select(Contact), caller, "contacts")
    if type:
        stmt = stmt.where(Contact.type == type)
    if q:
        has_phone = exists().where(
            ContactPhone.contact_id == Contact.id,
            ContactPhone.phone_e164.contains(q, autoescape=True),
        )
        stmt = stmt.where(
            or_(
                Contact.name.contains(q, autoescape=True),
                Contact.email.contains(q, autoescape=True),
                has_phone,
            )
        )
    column = SORTS[sort]
    contacts, total = paginate(
        db, stmt, params, column.desc() if order == "desc" else column.asc(), Contact.id
    )
    return Page(
        items=to_out(db, contacts), total=total, page=params.page, page_size=params.page_size
    )


@router.post("", response_model=ContactOut, status_code=status.HTTP_201_CREATED)
def create_contact(
    body: ContactIn,
    caller: AuthUser = Depends(require("contacts", "create")),
    db: Session = Depends(get_db),
) -> ContactOut:
    contact = Contact(
        name=body.name, type=body.type, email=body.email, notes=body.notes, owner_id=caller.id
    )
    db.add(contact)
    db.flush()
    replace_phones(db, contact.id, body.phones)
    db.commit()
    return to_out(db, [contact])[0]


@router.get("/{contact_id}", response_model=ContactOut)
def read_contact(
    contact_id: int, caller: AuthUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> ContactOut:
    return to_out(db, [get_scoped(db, caller, contact_id)])[0]


@router.put("/{contact_id}", response_model=ContactOut)
def update_contact(
    contact_id: int,
    body: ContactUpdate,
    caller: AuthUser = Depends(require("contacts", "update")),
    db: Session = Depends(get_db),
) -> ContactOut:
    contact = get_scoped(db, caller, contact_id)
    linked = db.scalars(select(User.id).where(User.contact_id == contact.id)).first()
    if linked and body.type == "entity":
        raise HTTPException(status.HTTP_409_CONFLICT, "a user's contact must be a person")
    contact.name, contact.type, contact.email, contact.notes = (
        body.name,
        body.type,
        body.email,
        body.notes,
    )
    if body.phones is not None:
        replace_phones(db, contact.id, body.phones)
    db.commit()
    return to_out(db, [contact])[0]


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contact(
    contact_id: int,
    caller: AuthUser = Depends(require("contacts", "delete")),
    db: Session = Depends(get_db),
) -> Response:
    contact = get_scoped(db, caller, contact_id)
    if db.scalars(select(User.id).where(User.contact_id == contact.id)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "contact is linked to an active user")
    now = utcnow()
    contact.deleted_at = now
    # Soft-delete the phones in the same transaction: that frees the numbers for reuse.
    db.execute(
        update(ContactPhone)
        .where(ContactPhone.contact_id == contact.id, ContactPhone.deleted_at.is_(None))
        .values(deleted_at=now)
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
