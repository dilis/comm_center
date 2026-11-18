"""Sending one Web Push: the payload, and telling the push service's answers apart.

The text of the SMS is never part of the payload: it would pass through third-party push services.
"""

import json
from dataclasses import dataclass

import requests
from pywebpush import WebPushException, webpush

from comm_center_notifier.config import settings

# A notification that could not be delivered within a day is not worth showing any more.
PUSH_TTL_SECONDS = 24 * 60 * 60
PUSH_TIMEOUT_SECONDS = 10
INBOUND_URL = "/messages?direction=received"


class PushError(Exception):
    """A push could not be delivered. ``retryable`` says whether trying again can help."""

    retryable = True


class PushGone(PushError):
    """The push service no longer knows this subscription (404 or 410): forget it."""

    retryable = False


class PushRejected(PushError):
    """The push service refused the request (another 4xx: bad keys, too large). It would fail every
    time, so it is not retried; the subscription itself may be fine."""

    retryable = False


@dataclass(frozen=True)
class Target:
    endpoint: str
    p256dh: str
    auth: str


def push_enabled() -> bool:
    return bool(settings.vapid_private_key and settings.vapid_subject)


def payload_for(count: int, senders: list[str], last_message_id: int | None) -> dict:
    """The notification for ``count`` received messages from ``senders`` (distinct names, in order
    of arrival; the list may be shorter than the count and is capped by the outbox)."""
    names = senders[:3]
    if len(names) > 1:
        who = ", ".join(names[:-1]) + " and " + names[-1]
    else:
        who = names[0] if names else "someone"
    if len(senders) > 3:
        who = ", ".join(names) + " and others"
    return {
        "title": "New message" if count == 1 else f"{count} new messages",
        "body": f"From {who}",
        "url": INBOUND_URL,
        "tag": f"message-{last_message_id}",
    }


def retry_delay(attempts: int) -> int:
    """Seconds to wait before the retry that follows the ``attempts``-th failed attempt."""
    return settings.push_retry_base_seconds * 2 ** (attempts - 1)


def send_push(target: Target, payload: dict) -> None:
    """Send one notification. Raises ``PushGone`` or ``PushError``."""
    try:
        webpush(
            subscription_info={
                "endpoint": target.endpoint,
                "keys": {"p256dh": target.p256dh, "auth": target.auth},
            },
            data=json.dumps(payload),
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject},  # pywebpush adds to this: pass a new one
            ttl=PUSH_TTL_SECONDS,
            timeout=PUSH_TIMEOUT_SECONDS,
        )
    except WebPushException as exc:
        status = getattr(exc.response, "status_code", None)
        if status in (404, 410):
            raise PushGone(str(exc)) from exc
        if status is not None and 400 <= status < 500 and status != 429:
            raise PushRejected(f"push service answered {status}: {exc}") from exc
        raise PushError(f"push service answered {status}: {exc}") from exc
    except requests.RequestException as exc:
        raise PushError(f"push service unreachable: {exc}") from exc
