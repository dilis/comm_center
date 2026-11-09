"""The API a worker program uses (SPECS.md 4.7). Workers always call the API, never the reverse."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import login_limits, security
from app.audit import client_ip, record_login
from app.clock import utcnow
from app.config import settings
from app.db import get_db
from app.deps import get_current_worker
from app.models import GsmDevice, WorkerAccount
from app.worker_accounts import authenticate_worker

log = logging.getLogger(__name__)
router = APIRouter(prefix="/worker", tags=["worker"])

# Bump when the worker endpoints change in a way an older worker cannot follow.
PROTOCOL_VERSION = 1


class WorkerTokenRequest(BaseModel):
    name: str
    secret: str


class WorkerToken(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class SessionRequest(BaseModel):
    version: str = Field(max_length=64)
    protocol_version: int
    providers: list[str]  # the provider types this worker can run


class SessionDevice(BaseModel):
    id: int
    name: str
    provider: str
    phone_number: str
    config: dict


class SessionOut(BaseModel):
    worker_id: int
    protocol_version: int
    devices: list[SessionDevice]


@router.post("/token", response_model=WorkerToken)
def token(body: WorkerTokenRequest, request: Request, db: Session = Depends(get_db)) -> WorkerToken:
    ip = client_ip(request)
    key = "worker:" + login_limits.normalize_username(body.name)  # apart from people's usernames
    wait = login_limits.blocked_for(db, login_limits.LOGIN, key, ip)
    if wait:
        log.warning("worker sign-in blocked for %r from %s", body.name[:64], ip)
        record_login(db, request, "worker_login_blocked", body.name)
        db.commit()
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "too many failed attempts; try again later",
            headers={"Retry-After": str(wait)},
        )
    worker = authenticate_worker(db, body.name, body.secret)
    if worker is None:
        record_login(db, request, "worker_login_failed", body.name)
        login_limits.record_failure(db, login_limits.LOGIN, key, ip)
        log.warning("failed worker sign-in for %r from %s", body.name[:64], ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    record_login(db, request, "worker_login", worker.name)
    login_limits.forget_failures(db, login_limits.LOGIN, key)  # commits the log row too
    access, _ = security.create_token(worker.id, "worker", settings.worker_token_ttl_seconds)
    return WorkerToken(access_token=access, expires_in=settings.worker_token_ttl_seconds)


@router.post("/session", response_model=SessionOut)
def session(
    body: SessionRequest,
    worker: WorkerAccount = Depends(get_current_worker),
    db: Session = Depends(get_db),
) -> SessionOut:
    """The handshake and heartbeat: records what the worker is, and tells it which devices to run."""
    if body.protocol_version != PROTOCOL_VERSION:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"unsupported protocol version {body.protocol_version}: this API speaks "
            f"protocol {PROTOCOL_VERSION}",
        )
    worker.version = body.version
    worker.protocol_version = body.protocol_version
    worker.last_seen_at = utcnow()
    devices = db.scalars(
        select(GsmDevice).where(GsmDevice.worker_id == worker.id).order_by(GsmDevice.id)
    ).all()
    db.commit()
    return SessionOut(
        worker_id=worker.id,
        protocol_version=PROTOCOL_VERSION,
        devices=[
            SessionDevice(
                id=d.id, name=d.name, provider=d.provider, phone_number=d.phone_number,
                config=d.config,
            )
            for d in devices
        ],
    )  # fmt: skip
