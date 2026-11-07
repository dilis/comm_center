"""Contact phone handling shared by the contacts, users and ``/auth/me`` endpoints."""

from collections.abc import Iterable

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.models import ContactPhone
from app.schemas import PhoneIn, PhoneOut


def phones_by_contact(db: Session, contact_ids: Iterable[int]) -> dict[int, list[PhoneOut]]:
    result: dict[int, list[PhoneOut]] = {}
    ids = list(contact_ids)
    if not ids:
        return result
    rows = db.scalars(
        select(ContactPhone).where(ContactPhone.contact_id.in_(ids)).order_by(ContactPhone.id)
    )
    for p in rows:
        result.setdefault(p.contact_id, []).append(
            PhoneOut(phone=p.phone_e164, label=p.label, is_primary=p.is_primary)
        )
    return result


def replace_phones(db: Session, contact_id: int, phones: list[PhoneIn]) -> None:
    """Make ``phones`` the contact's list: absent numbers are soft-deleted, new ones added.

    Flushes (does not commit). 422 for a duplicate or a second primary, 409 (after a rollback) when
    a number belongs to another contact.
    """
    numbers = [p.phone for p in phones]
    if len(set(numbers)) != len(numbers):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "duplicate phone number")
    if sum(p.is_primary for p in phones) > 1:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "only one primary phone")

    existing = {
        p.phone_e164: p
        for p in db.scalars(select(ContactPhone).where(ContactPhone.contact_id == contact_id))
    }
    now = utcnow()
    for number, row in existing.items():
        if number not in numbers:
            row.deleted_at = now
        else:
            row.is_primary = False
    try:
        db.flush()  # free the old primary and removed numbers before inserting
        for item in phones:
            row = existing.get(item.phone)
            if row is None:
                db.add(
                    ContactPhone(
                        contact_id=contact_id,
                        phone_e164=item.phone,
                        label=item.label,
                        is_primary=item.is_primary,
                    )
                )
            else:
                row.label, row.is_primary = item.label, item.is_primary
        db.flush()
    except DBAPIError as exc:
        db.rollback()
        if "uq_contact_phone_active_phone" in str(exc):
            raise HTTPException(status.HTTP_409_CONFLICT, "phone number already in use") from None
        raise
