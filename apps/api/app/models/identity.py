from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
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


class Contact(Base, OwnedMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "contacts"
    __table_args__ = (Index("ix_contacts_owner_id_deleted_at", "owner_id", "deleted_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # A person has a first name, maybe a middle name and a last name. An entity (a device, a
    # business) and a contact auto-created from an unknown number keep their whole name in
    # ``first_name``.
    first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    middle_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    # Generated (read-only): the parts joined by single spaces, for display, search and sorting.
    name: Mapped[str] = mapped_column(
        String(512), Computed("CONCAT_WS(' ', first_name, middle_name, last_name)", persisted=True)
    )
    type: Mapped[str] = mapped_column(
        Enum("person", "entity", name="contact_type"), nullable=False, server_default="person"
    )
    email: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)


class ContactPhone(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "contact_phone"
    __table_args__ = (
        CheckConstraint(r"phone_e164 REGEXP '^\\+[1-9][0-9]{6,14}$'", name="e164"),
        UniqueConstraint("active_phone", name="uq_contact_phone_active_phone"),
        UniqueConstraint("active_primary_contact_id", name="uq_contact_phone_active_primary"),
        Index("ix_contact_phone_contact_id", "contact_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    contact_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("contacts.id"), nullable=False)
    phone_e164: Mapped[str] = mapped_column(String(16), nullable=False)
    label: Mapped[str | None] = mapped_column(String(32))
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    # Generated columns: NULL once the row is soft-deleted, so unique indexes ignore deleted rows.
    active_phone: Mapped[str | None] = mapped_column(
        String(16), Computed("IF(deleted_at IS NULL, phone_e164, NULL)", persisted=False)
    )
    active_primary_contact_id: Mapped[int | None] = mapped_column(
        BigInteger,
        Computed("IF(deleted_at IS NULL AND is_primary = 1, contact_id, NULL)", persisted=False),
    )


class User(Base, OwnedMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "(is_system = 1 AND agent_direction IS NOT NULL)"
            " OR (is_system = 0 AND agent_direction IS NULL)",
            name="agent_direction_iff_system",
        ),
        CheckConstraint(
            "is_system = 0 OR login_enabled = 0",
            name="system_agent_cannot_log_in",
        ),
        CheckConstraint("is_system = 0 OR deleted_at IS NULL", name="system_agent_not_deletable"),
        UniqueConstraint("contact_id", name="uq_users_contact_id"),
        UniqueConstraint("active_username", name="uq_users_active_username"),
        Index("ix_users_owner_id_deleted_at", "owner_id", "deleted_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    contact_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("contacts.id"), nullable=False)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("1"))
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    agent_direction: Mapped[str | None] = mapped_column(
        Enum("inbound", "outbound", name="agent_direction")
    )
    login_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("1"))
    active_username: Mapped[str | None] = mapped_column(
        String(64), Computed("IF(deleted_at IS NULL, username, NULL)", persisted=False)
    )
