from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OwnedMixin, SoftDeleteMixin, TimestampMixin

E164 = r"REGEXP '^\\+[1-9][0-9]{6,14}$'"


class GsmDevice(Base, OwnedMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "gsm_device"
    __table_args__ = (
        CheckConstraint(f"phone_number {E164}", name="e164"),
        UniqueConstraint("agent_user_id", name="uq_gsm_device_agent_user_id"),
        Index("ix_gsm_device_owner_id_deleted_at", "owner_id", "deleted_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    serial_port: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("online", "offline", "error", name="gsm_device_status"),
        nullable=False,
        server_default="offline",
    )
    agent_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    # The latest modem problem, kept after recovery so people can see what went wrong and when.
    last_error: Mapped[str | None] = mapped_column(String(500))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime)


class Message(Base, OwnedMixin, TimestampMixin, SoftDeleteMixin):
    """An immutable log entry. Direction is derived from the owner, never stored."""

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(f"phone_number {E164}", name="e164"),
        Index("ix_messages_owner_id_deleted_at", "owner_id", "deleted_at"),
        Index("ix_messages_status_created_at", "status", "created_at"),
        Index("ix_messages_contact_id", "contact_id"),
        Index("ix_messages_reply_to_id", "reply_to_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    channel: Mapped[str] = mapped_column(Enum("gsm", name="message_channel"), nullable=False)
    contact_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("contacts.id"), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("queued", "sending", "sent", "failed", "delivered", "received", name="message_status"),
        nullable=False,
    )
    gsm_device_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("gsm_device.id"))
    # Set once at creation, for a reply: the received message it answers.
    reply_to_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("messages.id"))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    received_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(Text)


class MessageRead(Base):
    """A person has read a received message. Per user, kept apart from the immutable message."""

    __tablename__ = "message_read"
    __table_args__ = (Index("ix_message_read_message_id", "message_id"),)

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), primary_key=True)
    message_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("messages.id"), primary_key=True)
    read_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
