"""Inbound: store what the modem received, finding or creating the sender's contact."""

import logging
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models import Contact, ContactPhone, Message
from app.phones import normalize_e164
from app.worker.provider import ChannelProvider, InboundSms

log = logging.getLogger(__name__)


class DeviceRef(Protocol):
    id: int
    agent_user_id: int


def find_contact_id(db: Session, number: str) -> int | None:
    """The live contact that holds ``number``, if any (soft-deleted rows are invisible)."""
    return db.scalars(
        select(ContactPhone.contact_id)
        .join(Contact, Contact.id == ContactPhone.contact_id)
        .where(ContactPhone.phone_e164 == number)
    ).first()


def ingest(db: Session, device: DeviceRef, sms: InboundSms) -> Message | None:
    """Add ``sms`` to the database (the caller commits). None if the sender is not a phone number.

    An unknown sender gets a contact named after the number, owned by the device's agent. Two
    workers may race to create it; the unique index lets one win and the other re-reads.
    """
    try:
        number = normalize_e164(sms.sender)
    except ValueError:
        log.warning("dropping SMS from %r: sender is not a phone number", sms.sender)
        return None
    contact_id = find_contact_id(db, number)
    if contact_id is None:
        try:
            with db.begin_nested():
                contact = Contact(name=number, type="person", owner_id=device.agent_user_id)
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
        content=sms.content,
        status="received",
        owner_id=device.agent_user_id,  # owned by the device's inbound agent, so it is inbound
        received_at=sms.received_at,
    )
    db.add(message)
    db.flush()
    return message


def process_inbound(
    session_factory: sessionmaker, provider: ChannelProvider, device: DeviceRef
) -> int:
    """Poll the modem and store each message, acknowledging only after the commit (so a crash
    re-delivers rather than loses). Returns how many messages were stored."""
    stored = 0
    for sms in provider.poll_inbound():
        try:
            with session_factory() as db:
                message = ingest(db, device, sms)
                db.commit()
        except Exception:
            log.exception("could not store SMS %s; leaving it on the modem", sms.ref)
            continue
        provider.acknowledge(sms)  # also forgets unusable ones, or they would be polled forever
        stored += message is not None
    return stored
