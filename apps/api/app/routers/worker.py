"""The API a worker program uses (SPECS.md 4.7). Workers always call the API, never the reverse."""

import logging
from datetime import datetime, timedelta
from time import monotonic, sleep
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import dispatch, login_limits, security
from app.audit import client_ip, record_login
from app.clock import utcnow
from app.config import settings
from app.db import get_db
from app.deps import get_current_worker
from app.devices import authenticate_device
from app.inbound import store_inbound
from app.models import GsmDevice

log = logging.getLogger(__name__)
router = APIRouter(prefix="/worker", tags=["worker"])

# Bump when the worker endpoints change in a way an older worker cannot follow.
PROTOCOL_VERSION = 2


class WorkerTokenRequest(BaseModel):
    name: str  # the username of the device's agent, e.g. ``gsm-fake``
    secret: str


class WorkerToken(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class SessionRequest(BaseModel):
    version: str = Field(max_length=64)
    protocol_version: int
    # Random per running worker process. The same one again is a heartbeat; a new one means the
    # worker restarted, so whatever the old process was sending is failed (delivery unknown).
    instance_id: str = Field(min_length=1, max_length=64)


class SessionDevice(BaseModel):
    id: int
    name: str
    phone_number: str


class SessionOut(BaseModel):
    protocol_version: int
    devices: list[SessionDevice]  # the one device this worker serves


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
    device = authenticate_device(db, body.name, body.secret)
    if device is None:
        record_login(db, request, "worker_login_failed", body.name)
        login_limits.record_failure(db, login_limits.LOGIN, key, ip)
        log.warning("failed worker sign-in for %r from %s", body.name[:64], ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    record_login(db, request, "worker_login", body.name)
    login_limits.forget_failures(db, login_limits.LOGIN, key)  # commits the log row too
    access, _ = security.create_token(
        device.agent_user_id, "worker", settings.worker_token_ttl_seconds
    )
    return WorkerToken(access_token=access, expires_in=settings.worker_token_ttl_seconds)


@router.post("/session", response_model=SessionOut)
def session(
    body: SessionRequest,
    device: GsmDevice = Depends(get_current_worker),
    db: Session = Depends(get_db),
) -> SessionOut:
    """The handshake and heartbeat: records what the worker is, and tells it which device it serves."""
    if body.protocol_version != PROTOCOL_VERSION:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"unsupported protocol version {body.protocol_version}: this API speaks "
            f"protocol {PROTOCOL_VERSION}",
        )
    if device.instance_id != body.instance_id:
        dispatch.fail_device_leases(db, device.id)
        device.instance_id = body.instance_id
    device.version = body.version
    device.protocol_version = body.protocol_version
    device.last_seen_at = utcnow()
    db.commit()
    return SessionOut(
        protocol_version=PROTOCOL_VERSION,
        devices=[SessionDevice(id=device.id, name=device.name, phone_number=device.phone_number)],
    )


MAX_DEVICE_ERROR_LENGTH = 500  # the width of gsm_device.last_error
LONG_POLL_STEP_SECONDS = 1.0


def _own_device(device: GsmDevice, device_id: int) -> GsmDevice:
    """The worker serves one device; a request about any other is refused."""
    if device.id != device_id:
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
    own: GsmDevice = Depends(get_current_worker),
    db: Session = Depends(get_db),
) -> ClaimOut:
    """Hand the next queued message to the worker, leased to it for ``lease_seconds`` (extend or
    report before then). Waits up to ``wait_seconds`` for one to arrive."""
    device = _own_device(own, body.device_id)
    deadline = monotonic() + min(body.wait_seconds, settings.worker_long_poll_seconds)
    while True:
        dispatch.expire_leases(db)
        message = dispatch.claim_next(db, device)
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
    own: GsmDevice = Depends(get_current_worker),
    db: Session = Depends(get_db),
) -> Response:
    """What happened to a message the worker holds. ``sent`` means the device accepted it."""
    lease = dispatch.held_lease(db, own, message_id)
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
    own: GsmDevice = Depends(get_current_worker),
    db: Session = Depends(get_db),
) -> LeaseOut:
    lease = dispatch.held_lease(db, own, message_id)
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
    own: GsmDevice = Depends(get_current_worker),
    db: Session = Depends(get_db),
) -> InboundOut:
    """Store a received SMS, finding or creating the sender's contact. Answers 200 only after the
    commit, so the worker may then forget the message on the device."""
    device = _own_device(own, body.device_id)
    result = store_inbound(db, device, body.ref, body.sender, body.content, body.received_at)
    return InboundOut(
        stored=result.stored, duplicate=result.duplicate, message_id=result.message_id
    )


class DeviceStatusIn(BaseModel):
    status: Literal["online", "offline", "error"]
    error: str | None = None


@router.post("/devices/{device_id}/status", status_code=status.HTTP_204_NO_CONTENT)
def device_status(
    device_id: int,
    body: DeviceStatusIn,
    own: GsmDevice = Depends(get_current_worker),
    db: Session = Depends(get_db),
) -> Response:
    """Health of a device. An error is kept as history after the device recovers."""
    device = _own_device(own, device_id)
    device.status = body.status
    if body.error:
        device.last_error = body.error[:MAX_DEVICE_ERROR_LENGTH]
        device.last_error_at = utcnow()
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
