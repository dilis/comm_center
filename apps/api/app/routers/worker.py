"""The API a worker program uses (SPECS.md 4.7). Workers always call the API, never the reverse."""

import logging
from datetime import UTC, datetime, timedelta
from time import monotonic, sleep
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import dispatch, login_limits, security
from app.audit import client_ip, record_login
from app.clock import utcnow
from app.config import settings
from app.db import get_db
from app.deps import get_current_worker
from app.inbound import ingest_message
from app.models import GsmDevice, InboundRef, WorkerAccount
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
    # Random per running worker process. The same one again is a heartbeat; a new one means the
    # worker restarted, so whatever the old process was sending is failed (delivery unknown).
    instance_id: str = Field(min_length=1, max_length=64)


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
    if worker.instance_id != body.instance_id:
        dispatch.fail_worker_leases(db, worker.id)
        worker.instance_id = body.instance_id
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


MAX_DEVICE_ERROR_LENGTH = 500  # the width of gsm_device.last_error
LONG_POLL_STEP_SECONDS = 1.0


def _own_device(db: Session, worker: WorkerAccount, device_id: int) -> GsmDevice:
    device = db.scalars(
        select(GsmDevice).where(GsmDevice.id == device_id, GsmDevice.worker_id == worker.id)
    ).one_or_none()
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "device not found")
    return device


class ClaimRequest(BaseModel):
    device_id: int
    wait_seconds: float = Field(default=0, ge=0)  # long-poll; capped by WORKER_LONG_POLL_SECONDS


class ClaimedMessage(BaseModel):
    id: int
    phone_number: str
    content: str


class ClaimOut(BaseModel):
    message: ClaimedMessage | None
    lease_seconds: int


@router.post("/claim", response_model=ClaimOut)
def claim(
    body: ClaimRequest,
    worker: WorkerAccount = Depends(get_current_worker),
    db: Session = Depends(get_db),
) -> ClaimOut:
    """Hand the next queued message to the worker, leased to it for ``lease_seconds`` (extend or
    report before then). Waits up to ``wait_seconds`` for one to arrive."""
    device = _own_device(db, worker, body.device_id)
    deadline = monotonic() + min(body.wait_seconds, settings.worker_long_poll_seconds)
    while True:
        dispatch.expire_leases(db)
        message = dispatch.claim_next(db, worker, device.id)
        out = (
            ClaimedMessage(
                id=message.id, phone_number=message.phone_number, content=message.content
            )
            if message
            else None
        )
        db.commit()  # also ends the read snapshot between polls
        if out is not None or monotonic() >= deadline:
            return ClaimOut(message=out, lease_seconds=settings.worker_lease_seconds)
        sleep(LONG_POLL_STEP_SECONDS)


class ResultIn(BaseModel):
    status: Literal["sent", "failed"]
    error: str | None = None


@router.post("/messages/{message_id}/result", status_code=status.HTTP_204_NO_CONTENT)
def report_result(
    message_id: int,
    body: ResultIn,
    worker: WorkerAccount = Depends(get_current_worker),
    db: Session = Depends(get_db),
) -> Response:
    """What happened to a message the worker holds. ``sent`` means the device accepted it."""
    lease = dispatch.held_lease(db, worker, message_id)
    if lease is None:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "this worker does not hold that message")
    dispatch.finish(db, lease, body.status, body.error)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class LeaseOut(BaseModel):
    lease_seconds: int


@router.post("/messages/{message_id}/extend", response_model=LeaseOut)
def extend_lease(
    message_id: int,
    worker: WorkerAccount = Depends(get_current_worker),
    db: Session = Depends(get_db),
) -> LeaseOut:
    lease = dispatch.held_lease(db, worker, message_id)
    if lease is None:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "this worker does not hold that message")
    lease.expires_at = utcnow() + timedelta(seconds=settings.worker_lease_seconds)
    db.commit()
    return LeaseOut(lease_seconds=settings.worker_lease_seconds)


class InboundIn(BaseModel):
    device_id: int
    # The provider's own reference for the message; a repeat of the same one is stored once.
    ref: str = Field(min_length=1, max_length=255)
    sender: str = Field(min_length=1, max_length=64)  # as the network reports it
    content: str
    received_at: datetime


class InboundOut(BaseModel):
    stored: bool
    duplicate: bool
    message_id: int | None


@router.post("/inbound", response_model=InboundOut)
def inbound(
    body: InboundIn,
    worker: WorkerAccount = Depends(get_current_worker),
    db: Session = Depends(get_db),
) -> InboundOut:
    """Store a received SMS, finding or creating the sender's contact. Answers 200 only after the
    commit, so the worker may then forget the message on the device."""
    device = _own_device(db, worker, body.device_id)

    def seen() -> InboundOut | None:
        existing = db.scalars(
            select(InboundRef).where(InboundRef.device_id == device.id, InboundRef.ref == body.ref)
        ).one_or_none()
        if existing is None:
            return None
        return InboundOut(stored=False, duplicate=True, message_id=existing.message_id)

    if (dup := seen()) is not None:
        db.commit()
        return dup
    received = body.received_at
    if received.tzinfo is not None:
        received = received.astimezone(UTC).replace(tzinfo=None)
    try:
        with db.begin_nested():
            message = ingest_message(db, device.agent_user_id, body.sender, body.content, received)
            db.add(
                InboundRef(
                    device_id=device.id, ref=body.ref, message_id=message.id if message else None
                )
            )
            db.flush()
    except IntegrityError as exc:
        if "uq_inbound_ref_device_id_ref" not in str(exc):
            raise
        dup = seen()  # another request stored it first
        db.commit()
        if dup is None:
            raise
        return dup
    db.commit()
    return InboundOut(
        stored=message is not None, duplicate=False, message_id=message.id if message else None
    )


class DeviceStatusIn(BaseModel):
    status: Literal["online", "offline", "error"]
    error: str | None = None


@router.post("/devices/{device_id}/status", status_code=status.HTTP_204_NO_CONTENT)
def device_status(
    device_id: int,
    body: DeviceStatusIn,
    worker: WorkerAccount = Depends(get_current_worker),
    db: Session = Depends(get_db),
) -> Response:
    """Health of a device. An error is kept as history after the device recovers."""
    device = _own_device(db, worker, device_id)
    device.status = body.status
    if body.error:
        device.last_error = body.error[:MAX_DEVICE_ERROR_LENGTH]
        device.last_error_at = utcnow()
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
