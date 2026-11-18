"""The notifier's loop: send what the API queued in ``push_outbox`` (SPECS.md, Phase 9).

Each cycle it claims the rows that are due, oldest first, and sends them one by one. A failed send
is planned for a retry further in the future, so the other recipients are always tried first; a row
that keeps failing is given up on. Nothing is sent while push is not configured.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from comm_center_notifier import outbox, sender
from comm_center_notifier.config import settings
from comm_center_notifier.db import Connect

log = logging.getLogger(__name__)

BATCH = 20  # rows claimed per cycle


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)  # the database stores naive UTC


def _send(connect: Connect, row_id: int, now: datetime) -> None:
    conn = connect()
    try:
        row = outbox.get(conn, row_id)
        if row is None or row["state"] != "sending":
            return
        sub = outbox.subscription(conn, row["subscription_id"])
        if sub is None:
            outbox.delete_row(conn, row_id)
            conn.commit()
            return
        target = sender.Target(sub["endpoint"], sub["p256dh"], sub["auth"])
        payload = sender.payload_for(row["message_count"], row["senders"], row["last_message_id"])
        conn.commit()  # no transaction stays open while the push service answers
        outcome: Exception | None = None
        try:
            sender.send_push(target, payload)
        except Exception as exc:  # noqa: BLE001 - whatever happens, the row must leave `sending`
            outcome = exc
        row = outbox.get(conn, row_id)
        if row is None:
            return
        if outcome is None:
            outbox.delete_row(conn, row_id)
        elif isinstance(outcome, sender.PushGone):
            outbox.delete_subscription(conn, sub["id"])
        elif isinstance(outcome, sender.PushError) and not outcome.retryable:
            log.error("push rejected, not retrying: %s", outcome)
            outbox.delete_row(conn, row_id)
        else:
            if not isinstance(outcome, sender.PushError):
                log.warning("push failed unexpectedly", exc_info=outcome)
            _fail(conn, row, now, str(outcome) or type(outcome).__name__)
        conn.commit()
    finally:
        conn.close()


def _fail(conn, row: outbox.Row, now: datetime, error: str) -> None:
    row["attempts"] += 1
    if row["attempts"] >= settings.push_max_attempts:
        log.warning("giving up on a push after %s attempts: %s", row["attempts"], error)
        outbox.delete_row(conn, row["id"])
        return
    delay = timedelta(seconds=sender.retry_delay(row["attempts"]))
    outbox.requeue(conn, row, now + delay, error[:255])


def run_once(connect: Connect, now: datetime | None = None) -> int:
    """One cycle: recover abandoned rows, claim what is due and send it. Returns how many were
    sent or tried."""
    if not sender.push_enabled():
        return 0
    now = now or utcnow()
    conn = connect()
    try:
        outbox.reset_stale(conn, now)
        claimed = outbox.claim(conn, now, settings.notifier_lease_seconds, BATCH)
        conn.commit()
    finally:
        conn.close()
    for row_id in claimed:
        _send(connect, row_id, now)
    return len(claimed)


def run_loop(
    connect: Connect,
    *,
    heartbeat: Callable[[], None],
    sleep: Callable[[float], None],
    stop: Callable[[], bool],
) -> None:
    while not stop():
        busy = 0
        try:
            busy = run_once(connect, utcnow())
        except Exception:
            log.exception("notifier cycle failed")  # the database may be briefly away
        heartbeat()
        if busy < BATCH:
            sleep(settings.notifier_poll_seconds)
