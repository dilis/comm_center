"""Inbound: store what the modem received, finding or creating the sender's contact."""

import logging
from typing import Protocol

from sqlalchemy.orm import Session, sessionmaker

from app.inbound import ingest_message
from app.models import Message
from app.worker.provider import ChannelProvider, InboundSms

log = logging.getLogger(__name__)


class DeviceRef(Protocol):
    id: int
    agent_user_id: int


def ingest(db: Session, device: DeviceRef, sms: InboundSms) -> Message | None:
    """Add ``sms`` to the database (the caller commits). None if the sender is not a phone number."""
    return ingest_message(db, device.agent_user_id, sms.sender, sms.content, sms.received_at)


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
