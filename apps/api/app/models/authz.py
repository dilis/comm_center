from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OwnedMixin, SoftDeleteMixin, TimestampMixin


class Permission(Base):
    __tablename__ = "permission"
    __table_args__ = (UniqueConstraint("resource", "action", name="uq_permission_resource_action"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    resource: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)


class AccessGroup(Base, OwnedMixin, TimestampMixin, SoftDeleteMixin):
    """A named set of permissions. (Not called ``groups``: that is reserved in MySQL 8.)"""

    __tablename__ = "access_group"
    __table_args__ = (
        UniqueConstraint("active_name", name="uq_access_group_active_name"),
        Index("ix_access_group_owner_id_deleted_at", "owner_id", "deleted_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    active_name: Mapped[str | None] = mapped_column(
        String(64), Computed("IF(deleted_at IS NULL, name, NULL)", persisted=False)
    )


class GroupPermission(Base):
    __tablename__ = "group_permission"

    group_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("access_group.id"), primary_key=True
    )
    permission_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("permission.id"), primary_key=True
    )


class GroupGroup(Base):
    """Direct nesting: ``parent`` includes ``child``."""

    __tablename__ = "group_group"
    __table_args__ = (CheckConstraint("parent_id <> child_id", name="no_self_nesting"),)

    parent_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("access_group.id"), primary_key=True
    )
    child_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("access_group.id"), primary_key=True
    )


class GroupClosure(Base):
    """Precomputed transitive nesting, including each group paired with itself."""

    __tablename__ = "group_closure"

    ancestor_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("access_group.id"), primary_key=True
    )
    descendant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("access_group.id"), primary_key=True
    )


class UserGroup(Base):
    __tablename__ = "user_group"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), primary_key=True)
    group_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("access_group.id"), primary_key=True
    )
