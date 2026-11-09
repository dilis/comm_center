"""Storing a received SMS, finding or creating the sender's contact. Used by the worker API."""

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Contact, ContactPhone, Message
from app.phones import normalize_e164

log = logging.getLogger(__name__)


def find_contact_id(db: Session, number: str) -> int | None:
    """The live contact that holds ``number``, if any (soft-deleted rows are invisible)."""
    return db.scalars(
        select(ContactPhone.contact_id)
        .join(Contact, Contact.id == ContactPhone.contact_id)
        .where(ContactPhone.phone_e164 == number)
    ).first()


def ingest_message(
    db: Session, agent_user_id: int, sender: str, content: str, received_at: datetime
) -> Message | None:
    """Add a received SMS to the database (the caller commits). None if the sender is not a phone
    number. ``agent_user_id`` is the receiving device's inbound agent, which owns the message.

    An unknown sender gets a contact named after the number, owned by that agent. Two writers may
    race to create it; the unique index lets one win and the other re-reads.
    """
    try:
        number = normalize_e164(sender)
    except ValueError:
        log.warning("dropping SMS from %r: sender is not a phone number", sender)
        return None
    contact_id = find_contact_id(db, number)
    if contact_id is None:
        try:
            with db.begin_nested():
                contact = Contact(name=number, type="person", owner_id=agent_user_id)
                db.add(contact)
                db.flush()
                db.add(ContactPhone(contact_id=contact.id, phone_e164=number, is_primary=True))
                db.flush()
            contact_id = contact.id
        except IntegrityError as exc:
            if "uq_contact_phone_active_phone" not in str(exc):
                raise
            contact_id = find_contact_id(db, number)  # the other writer's contact
            if contact_id is None:
                raise
    message = Message(
        channel="gsm",
        contact_id=contact_id,
        phone_number=number,
        content=content,
        status="received",
        owner_id=agent_user_id,  # owned by the device's inbound agent, so it is inbound
        received_at=received_at,
    )
    db.add(message)
    db.flush()
    return message
