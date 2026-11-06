from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, MetaData, event, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, with_loader_criteria

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class SoftDeleteMixin:
    """Rows are never removed; ``deleted_at`` marks them deleted. ORM selects hide them by default."""

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class OwnedMixin:
    """Every resource has an owner: the creating user, or a system agent for system-made rows."""

    owner_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)


@event.listens_for(Session, "do_orm_execute")
def _hide_soft_deleted(state) -> None:
    """Add ``deleted_at IS NULL`` to every ORM select unless ``include_deleted=True`` is set."""
    if state.is_select and not state.execution_options.get("include_deleted", False):
        state.statement = state.statement.options(
            with_loader_criteria(
                SoftDeleteMixin,
                lambda cls: cls.deleted_at.is_(None),
                include_aliases=True,
            )
        )
