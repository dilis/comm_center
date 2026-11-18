"""The outbox, in plain SQL (contract/outbox.sql). Every function works inside the caller's
transaction; the caller commits.

Rows are found with a plain read and locked by primary key: a locking read over a range would take
gap locks, which deadlock against the API queueing a message for the same subscription.
"""

import json
from datetime import datetime, timedelta

import pymysql

MAX_SENDERS = 4  # distinct names kept (one more than a notification shows, to say "and others")
Row = dict


def _parse(row: Row | None) -> Row | None:
    if row is not None and isinstance(row["senders"], (str, bytes)):
        row["senders"] = json.loads(row["senders"])
    return row


def merge_senders(first: list[str], second: list[str]) -> list[str]:
    merged: list[str] = []
    for name in [*first, *second]:
        if name not in merged:
            merged.append(name)
    return merged[:MAX_SENDERS]


def get(conn: pymysql.Connection, row_id: int, *, lock: bool = False) -> Row | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM push_outbox WHERE id = %s" + (" FOR UPDATE SKIP LOCKED" if lock else ""),
            [row_id],
        )
        return _parse(cur.fetchone())


def subscription(conn: pymysql.Connection, subscription_id: int) -> Row | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM push_subscription WHERE id = %s", [subscription_id])
        return cur.fetchone()


def delete_row(conn: pymysql.Connection, row_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM push_outbox WHERE id = %s", [row_id])


def delete_subscription(conn: pymysql.Connection, subscription_id: int) -> None:
    """The push service forgot it; its outbox rows go with it (ON DELETE CASCADE)."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM push_subscription WHERE id = %s", [subscription_id])


def claim(conn: pymysql.Connection, now: datetime, lease_seconds: int, batch: int) -> list[int]:
    """Due rows, oldest ``send_after`` first, marked ``sending`` with a lease. Retries sit further
    in the future, so everyone else is claimed before them."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM push_outbox WHERE state = 'pending' AND send_after <= %s "
            "ORDER BY send_after, id LIMIT %s",
            [now, batch],
        )
        ids = [r["id"] for r in cur.fetchall()]
        claimed = []
        for row_id in ids:
            cur.execute(
                "SELECT id FROM push_outbox WHERE id = %s AND state = 'pending' "
                "FOR UPDATE SKIP LOCKED",
                [row_id],
            )
            if cur.fetchone() is None:
                continue
            cur.execute(
                "UPDATE push_outbox SET state = 'sending', lease_until = %s WHERE id = %s",
                [now + timedelta(seconds=lease_seconds), row_id],
            )
            claimed.append(row_id)
    return claimed


def reset_stale(conn: pymysql.Connection, now: datetime) -> None:
    """A row still ``sending`` after its lease means the notifier died with it: send it again."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM push_outbox WHERE state = 'sending' AND lease_until < %s", [now]
        )
        ids = [r["id"] for r in cur.fetchall()]
    for row_id in ids:
        row = get(conn, row_id, lock=True)
        if row is not None and row["state"] == "sending":
            requeue(conn, row, now, "lease expired")


def _pending_for(conn: pymysql.Connection, subscription_id: int, not_id: int) -> Row | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM push_outbox WHERE subscription_id = %s AND state = 'pending' "
            "AND id <> %s",
            [subscription_id, not_id],
        )
        found = cur.fetchone()
        if found is None:
            return None
        cur.execute(
            "SELECT * FROM push_outbox WHERE id = %s AND state = 'pending' FOR UPDATE",
            [found["id"]],
        )
        return _parse(cur.fetchone())


def requeue(conn: pymysql.Connection, row: Row, send_after: datetime, error: str | None) -> None:
    """Put a row that was being sent back to ``pending`` (``row["attempts"]`` is already counted).
    If a newer pending row for the same subscription exists (a message arrived meanwhile), merge
    into that one instead, so there is still one notification."""
    for _ in range(3):
        newer = _pending_for(conn, row["subscription_id"], row["id"])
        with conn.cursor() as cur:
            if newer is not None:
                senders = merge_senders(newer["senders"], row["senders"])
                cur.execute(
                    "UPDATE push_outbox SET message_count = %s, senders = %s, attempts = %s, "
                    "send_after = %s, last_error = %s WHERE id = %s",
                    [
                        newer["message_count"] + row["message_count"],
                        json.dumps(senders),
                        max(newer["attempts"], row["attempts"]),
                        max(newer["send_after"], send_after),  # a retry still waits its turn
                        error,
                        newer["id"],
                    ],
                )
                cur.execute("DELETE FROM push_outbox WHERE id = %s", [row["id"]])
                return
            try:
                cur.execute(
                    "UPDATE push_outbox SET state = 'pending', lease_until = NULL, "
                    "send_after = %s, last_error = %s, attempts = %s WHERE id = %s",
                    [send_after, error, row["attempts"], row["id"]],
                )
                return
            except pymysql.err.IntegrityError:
                continue  # the API queued a pending row just now: merge into it on the next pass
    raise RuntimeError("could not put the push back: the outbox row keeps changing")
