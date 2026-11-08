from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ActivityLog(Base):
    """What a signed-in person did (append-only). Never holds message text or passwords."""

    __tablename__ = "activity_log"
    __table_args__ = (
        Index("ix_activity_log_created_at", "created_at"),
        Index("ix_activity_log_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    resource: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[int | None] = mapped_column(BigInteger)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    ip: Mapped[str] = mapped_column(String(45), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class LoginLog(Base):
    """Sign-in history (append-only): successes, failures, blocks, sign-outs. ``user_id`` is
    empty when the username does not exist."""

    __tablename__ = "login_log"
    __table_args__ = (
        Index("ix_login_log_created_at", "created_at"),
        Index("ix_login_log_username_created_at", "username", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event: Mapped[str] = mapped_column(String(24), nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    ip: Mapped[str] = mapped_column(String(45), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
