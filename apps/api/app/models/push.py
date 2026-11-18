from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PushSubscription(Base):
    """One browser a person has allowed to show notifications (Web Push). Bookkeeping, not a
    resource: rows are deleted outright (by the person, or when the push service forgets them)."""

    __tablename__ = "push_subscription"
    __table_args__ = (
        UniqueConstraint("endpoint_hash", name="uq_push_subscription_endpoint_hash"),
        Index("ix_push_subscription_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    # SHA-256 of the endpoint: endpoints are too long for a unique index.
    endpoint_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    p256dh: Mapped[str] = mapped_column(String(255), nullable=False)
    auth: Mapped[str] = mapped_column(String(255), nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class PushOutbox(Base):
    """A notification waiting to go to one subscription, written when a message is stored and sent by
    the notifier. A subscription has at most one ``pending`` row: later messages join it, so a burst
    becomes one notification. A row being sent is ``sending`` (with a lease) and is not joined."""

    __tablename__ = "push_outbox"
    __table_args__ = (
        UniqueConstraint("pending_key", name="uq_push_outbox_pending_key"),
        CheckConstraint("state IN ('pending', 'sending')", name="state"),
        Index("ix_push_outbox_state_send_after", "state", "send_after"),
        Index("ix_push_outbox_subscription_id", "subscription_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    subscription_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("push_subscription.id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(8), nullable=False, server_default="pending")
    # Set only while pending: the unique index then allows one waiting row per subscription.
    pending_key: Mapped[int | None] = mapped_column(
        BigInteger, Computed("IF(state = 'pending', subscription_id, NULL)", persisted=False)
    )
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    last_message_id: Mapped[int | None] = mapped_column(BigInteger)
    senders: Mapped[list] = mapped_column(JSON, nullable=False)  # up to a few distinct names
    send_after: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
