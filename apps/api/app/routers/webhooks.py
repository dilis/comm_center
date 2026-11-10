"""Webhooks from the Android SMS gateway app. Each device signs its requests with its own key
(see ``app.webhooks``); there is no other authentication."""

import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import dispatch, webhooks
from app.db import get_db
from app.inbound import store_inbound
from app.models import GsmDevice

log = logging.getLogger(__name__)
router = APIRouter(prefix="/devices", tags=["webhooks"])

MAX_BODY_BYTES = 256 * 1024


def _refused() -> HTTPException:
    # One answer for an unknown device and a bad signature, so nothing
    # reveals which device ids exist.
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid signature")


def _bad(reason: str) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, reason)


def _parse_time(value: object) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    raise _bad("receivedAt is missing or not a time")


def _received(db: Session, device: GsmDevice, envelope: dict, payload: dict) -> dict:
    sender = payload.get("sender") or payload.get("phoneNumber")  # older apps said phoneNumber
    content = payload.get("message")
    if not isinstance(sender, str) or not sender or not isinstance(content, str):
        raise _bad("sms:received needs a sender and a message")
    # An event keeps its id when the app retries it; two messages with the same text do not share
    # one. Fall back to the app's message id only if the event carries none.
    event_id = envelope.get("id") or payload.get("messageId")
    if not isinstance(event_id, str) or not event_id:
        raise _bad("the event has no id")
    result = store_inbound(
        db, device, f"wh:{event_id}"[:255], sender, content, _parse_time(payload.get("receivedAt"))
    )
    return {
        "ignored": False,
        "stored": result.stored,
        "duplicate": result.duplicate,
        "message_id": result.message_id,
    }


def _delivery(db: Session, device: GsmDevice, event: str, payload: dict) -> dict:
    message_id = dispatch.parse_gateway_message_id(payload.get("messageId"))
    if message_id is None:
        return {"ignored": True}  # not one of ours (sent from the phone's own app, say)
    if event == "sms:sent":
        return {"ignored": False}  # the worker already marked it sent when the phone accepted it
    reason = payload.get("reason")
    changed = dispatch.apply_delivery_report(
        db,
        device.id,
        message_id,
        "delivered" if event == "sms:delivered" else "failed",
        reason if isinstance(reason, str) else None,
    )
    db.commit()
    return {"ignored": not changed}


def _handle(db: Session, device_id: int, body: bytes, timestamp: str | None, signature: str | None):
    if not webhooks.verify(device_id, body, timestamp, signature):
        raise _refused()
    device = db.scalars(select(GsmDevice).where(GsmDevice.id == device_id)).one_or_none()
    if device is None:
        raise _refused()
    try:
        envelope = json.loads(body)
    except ValueError:
        raise _bad("the body is not JSON") from None
    if not isinstance(envelope, dict) or not isinstance(envelope.get("payload", {}), dict):
        raise _bad("the body is not a webhook event")
    event, payload = envelope.get("event"), envelope.get("payload", {})
    if event == "sms:received":
        return _received(db, device, envelope, payload)
    if event in ("sms:sent", "sms:delivered", "sms:failed"):
        return _delivery(db, device, event, payload)
    return {"ignored": True}  # the app also offers pings, MMS and batches; answer 200 so it stops


@router.post("/{device_id}/webhook")
async def webhook(device_id: int, request: Request, db: Session = Depends(get_db)) -> dict:
    """An event from the phone. Answers 200 only after the work is committed, because the app
    keeps retrying anything else for days."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise _bad("body too large")
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise _bad("body too large")
    return await run_in_threadpool(
        _handle,
        db,
        device_id,
        body,
        request.headers.get("x-timestamp"),
        request.headers.get("x-signature"),
    )
