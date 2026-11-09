"""Storing a received SMS, finding or creating the sender's contact. Used by the worker API."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Contact, ContactPhone, GsmDevice, InboundRef, Message
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


@dataclass(frozen=True)
class Stored:
    stored: bool  # a message was added
    duplicate: bool  # this ref was handed over before: nothing was added
    message_id: int | None


def to_utc_naive(moment: datetime) -> datetime:
    """The database keeps naive UTC. A time without a zone is taken to be UTC already."""
    if moment.tzinfo is None:
        return moment
    return moment.astimezone(UTC).replace(tzinfo=None)


def store_inbound(
    db: Session, device: GsmDevice, ref: str, sender: str, content: str, received_at: datetime
) -> Stored:
    """Store a received SMS once per ``(device, ref)`` and commit. Used by the worker API and by the
    Android webhook, which both answer success only after this returns, so the sender may forget
    the message. A repeat of a ref changes nothing; a sender that is not a phone number is dropped
    but its ref is remembered."""

    def seen() -> Stored | None:
        existing = db.scalars(
            select(InboundRef).where(InboundRef.device_id == device.id, InboundRef.ref == ref)
        ).one_or_none()
        if existing is None:
            return None
        return Stored(stored=False, duplicate=True, message_id=existing.message_id)

    if (dup := seen()) is not None:
        db.commit()
        return dup
    try:
        with db.begin_nested():
            message = ingest_message(
                db, device.agent_user_id, sender, content, to_utc_naive(received_at)
            )
            db.add(
                InboundRef(device_id=device.id, ref=ref, message_id=message.id if message else None)
            )
            db.flush()
    except IntegrityError as exc:
        if "uq_inbound_ref_device_id_ref" not in str(exc):
            raise
        dup = seen()  # another request stored it first
        db.commit()
        if dup is None:
            raise
        return dup
    db.commit()
    return Stored(
        stored=message is not None, duplicate=False, message_id=message.id if message else None
    )
