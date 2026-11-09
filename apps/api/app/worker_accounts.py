"""Worker accounts: programs (not people) that are expected to connect to the API."""

import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import security
from app.bootstrap import SYSTEM_USER_ID
from app.models import WorkerAccount

# A worker is told apart from a person by its own token kind, so a worker token never works on a
# user endpoint and the other way round.


class WorkerError(Exception):
    pass


def create_worker(db: Session, name: str) -> tuple[WorkerAccount, str]:
    """Register a worker. Returns it with its secret, which is not stored and cannot be shown
    again. Commits."""
    name = name.strip()
    if not name or len(name) > 64:
        raise WorkerError("a worker name of 1 to 64 characters is required")
    secret = secrets.token_urlsafe(32)
    worker = WorkerAccount(
        name=name, secret_hash=security.hash_password(secret), owner_id=SYSTEM_USER_ID
    )
    db.add(worker)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if "uq_worker_account_name" in str(exc):
            raise WorkerError(f"worker {name!r} already exists") from None
        raise
    return worker, secret


def authenticate_worker(db: Session, name: str, secret: str) -> WorkerAccount | None:
    """The worker if the secret matches; always does one hash check, so timing does not reveal
    which names exist."""
    worker = db.scalars(select(WorkerAccount).where(WorkerAccount.name == name)).one_or_none()
    hash_ = worker.secret_hash if worker else security.DUMMY_HASH
    valid = security.verify_password(hash_, secret)
    return worker if worker and valid else None
