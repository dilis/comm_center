from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MessageLease(Base):
    """A device's hold on a message it is sending. Bookkeeping kept apart from the message, which
    stays immutable. A lease that runs out fails the message; it is never handed out again."""

    __tablename__ = "message_lease"
    __table_args__ = (Index("ix_message_lease_expires_at", "expires_at"),)

    message_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("messages.id"), primary_key=True, autoincrement=False
    )
    device_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("gsm_device.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class InboundRef(Base):
    """A received message a device has already handed over, by the provider's own reference, so a
    retry (a lost answer, a webhook sent twice) is stored once. ``message_id`` is empty when the
    message was dropped (sender not a phone number)."""

    __tablename__ = "inbound_ref"
    __table_args__ = (UniqueConstraint("device_id", "ref", name="uq_inbound_ref_device_id_ref"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("gsm_device.id"), nullable=False)
    ref: Mapped[str] = mapped_column(String(255), nullable=False)
    message_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("messages.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
