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


class Message(Base, OwnedMixin, TimestampMixin, SoftDeleteMixin):
    """An immutable log entry. Direction is derived from the owner, never stored."""

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(f"phone_number {E164}", name="e164"),
        Index("ix_messages_owner_id_deleted_at", "owner_id", "deleted_at"),
        Index("ix_messages_status_created_at", "status", "created_at"),
        Index("ix_messages_contact_id", "contact_id"),
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
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    received_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(Text)
