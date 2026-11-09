from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OwnedMixin, SoftDeleteMixin, TimestampMixin


class WorkerAccount(Base, OwnedMixin, TimestampMixin, SoftDeleteMixin):
    """A worker program that is expected to connect (never a person). It signs in with its name
    and a secret that is shown once and stored only as a hash."""

    __tablename__ = "worker_account"
    __table_args__ = (UniqueConstraint("name", name="uq_worker_account_name"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    secret_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # what the worker reported in its latest session
    version: Mapped[str | None] = mapped_column(String(64))
    protocol_version: Mapped[int | None] = mapped_column(Integer)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
