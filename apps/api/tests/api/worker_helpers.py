"""Shared setup for the worker endpoint tests."""

from sqlalchemy import text

from app.devices import register_device
from app.worker_accounts import create_worker

PHONE = "+639171234567"


def sign_in(client, name, secret) -> dict:
    r = client.post("/worker/token", json={"name": name, "secret": secret})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def make_worker_with_device(client, db, worker="w1", device="d1", number="+639170000000"):
    """A worker, one device assigned to it, and the worker's auth headers."""
    _, secret = create_worker(db, worker)
    dev = register_device(db, device, "x", number, worker=worker)
    return sign_in(client, worker, secret), dev


def message_row(db, message_id):
    return db.execute(
        text(
            "SELECT status, sent_at, error_message, gsm_device_id, deleted_at "
            "FROM messages WHERE id=:i"
        ),
        {"i": message_id},
    ).one()


def lease_row(db, message_id):
    return db.execute(
        text("SELECT worker_id, device_id, expires_at FROM message_lease WHERE message_id=:i"),
        {"i": message_id},
    ).one_or_none()
