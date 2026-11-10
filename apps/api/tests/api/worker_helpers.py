"""Shared setup for the worker endpoint tests."""

from sqlalchemy import text

from app.devices import register_device

PHONE = "+639171234567"
SECRET = "a-long-enough-worker-secret"


def sign_in(client, name, secret) -> dict:
    r = client.post("/worker/token", json={"name": name, "secret": secret})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def make_worker_with_device(client, db, device="d1", number="+639170000000"):
    """A device, and the auth headers of its worker (which signs in as the device's agent)."""
    dev = register_device(db, device, number, secret=SECRET)
    return sign_in(client, f"gsm-{device}", SECRET), dev


def other_worker(client, db, device="d2", number="+639170000001"):
    """Another device with a worker of its own."""
    return make_worker_with_device(client, db, device, number)


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
        text("SELECT device_id, expires_at FROM message_lease WHERE message_id=:i"),
        {"i": message_id},
    ).one_or_none()
