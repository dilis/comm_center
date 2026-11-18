"""The push outbox: what the API queues when a message arrives (SPECS.md, Phase 9). The notifier
(``apps/notifier``) sends it; the tables are their contract (``apps/notifier/contract/outbox.sql``).

A subscription has at most one ``pending`` row. A message that arrives while one waits joins it (the
count goes up, the sender is added, the send time stays), so a burst, or a retry that is waiting,
becomes a single notification.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.config import settings
from app.models import Contact, Message, PushOutbox, PushSubscription
from app.push import inbound_recipients, push_enabled

log = logging.getLogger(__name__)

MAX_SENDERS = 4  # distinct names kept (one more than a notification shows, to say "and others")


def merge_senders(first: list[str], second: list[str]) -> list[str]:
    merged: list[str] = []
    for name in [*first, *second]:
        if name not in merged:
            merged.append(name)
    return merged[:MAX_SENDERS]


def _pending(db: Session, subscription_id: int) -> PushOutbox | None:
    """The waiting row of a subscription, locked. Found with a plain read and locked by primary
    key: a locking read over a range would take gap locks, which deadlock against the notifier."""
    row_id = db.scalars(
        select(PushOutbox.id).where(
            PushOutbox.subscription_id == subscription_id, PushOutbox.state == "pending"
        )
    ).first()
    if row_id is None:
        return None
    return db.scalars(
        select(PushOutbox)
        .where(PushOutbox.id == row_id, PushOutbox.state == "pending")
        .with_for_update()
    ).one_or_none()


def add_to_outbox(
    db: Session, subscription_id: int, message_id: int, sender: str, now: datetime | None = None
) -> None:
    """Queue one received message for one subscription, joining the waiting notification if any."""
    now = now or utcnow()
    for _ in range(3):  # two writers can both find nothing; the unique index lets one win
        row = _pending(db, subscription_id)
        if row is not None:
            row.message_count += 1
            row.last_message_id = message_id
            row.senders = merge_senders(row.senders, [sender])
            db.flush()
            return
        try:
            with db.begin_nested():
                db.add(
                    PushOutbox(
                        subscription_id=subscription_id,
                        state="pending",
                        message_count=1,
                        last_message_id=message_id,
                        senders=[sender],
                        send_after=now + timedelta(seconds=settings.push_aggregate_seconds),
                        attempts=0,
                    )
                )
                db.flush()
            return
        except IntegrityError as exc:
            if "uq_push_outbox_pending_key" not in str(exc):
                raise
    raise RuntimeError("could not queue a push: the outbox row keeps changing")


def enqueue_inbound(db: Session, message: Message, now: datetime | None = None) -> None:
    """Queue a push for everyone who may see this received message. The caller commits."""
    if not push_enabled():
        return
    contact = db.get(Contact, message.contact_id)
    sender = contact.name if contact else message.phone_number
    subscriptions = db.scalars(
        select(PushSubscription.id).where(PushSubscription.user_id.in_(inbound_recipients(db)))
    ).all()
    for subscription_id in subscriptions:
        add_to_outbox(db, subscription_id, message.id, sender, now)
