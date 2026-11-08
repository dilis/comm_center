from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RefreshToken(Base):
    """One issued refresh token (identified by its JWT ``jti``). Rotated on every use."""

    __tablename__ = "refresh_token"
    __table_args__ = (
        UniqueConstraint("jti", name="uq_refresh_token_jti"),
        Index("ix_refresh_token_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    jti: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class LoginAttempt(Base):
    """A failed sign-in, kept briefly to rate limit by username and by client address."""

    __tablename__ = "login_attempt"
    __table_args__ = (
        Index("ix_login_attempt_username_created_at", "username", "created_at"),
        Index("ix_login_attempt_ip_created_at", "ip", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(255), nullable=False)  # normalized, may not exist
    ip: Mapped[str] = mapped_column(String(45), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
