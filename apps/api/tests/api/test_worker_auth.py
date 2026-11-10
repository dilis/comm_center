"""A worker signs in with its name and secret and gets a short-lived worker token."""

import pytest
from sqlalchemy import text

from app import security
from app.config import settings
from app.devices import register_device, set_device_secret
from tests.api.conftest import auth_header
from tests.db.helpers import make_login_user

pytestmark = pytest.mark.db


@pytest.fixture
def worker(db):
    """A device and the secret its worker signs in with, as the device's agent ``gsm-lab-pc``."""
    device = register_device(db, "lab-pc", "+639170000001")
    secret = set_device_secret(db, "lab-pc")
    return device, secret


def token(client, name, secret):
    return client.post("/worker/token", json={"name": name, "secret": secret})


def test_valid_credentials_give_a_worker_token(client, worker):
    _, secret = worker
    r = token(client, "gsm-lab-pc", secret)
    assert r.status_code == 200
    body = r.json()
    assert (
        body["token_type"] == "bearer" and body["expires_in"] == settings.worker_token_ttl_seconds
    )
    claims = security.decode_token(body["access_token"], "worker")
    assert claims["sub"] == str(worker[0].agent_user_id)


@pytest.mark.parametrize("name,secret", [("gsm-lab-pc", "wrong"), ("nobody", "whatever")])
def test_bad_credentials_are_refused_the_same_way(client, worker, name, secret):
    r = token(client, name, secret)
    assert r.status_code == 401 and r.json() == {"detail": "invalid credentials"}


def test_a_deleted_device_cannot_sign_in(client, worker, db):
    device, secret = worker
    db.execute(text("UPDATE gsm_device SET deleted_at = NOW() WHERE id = :i"), {"i": device.id})
    db.commit()
    assert token(client, "gsm-lab-pc", secret).status_code == 401


def test_a_deactivated_agent_cannot_sign_in(client, worker, db):
    device, secret = worker
    db.execute(text("UPDATE users SET is_active = 0 WHERE id = :i"), {"i": device.agent_user_id})
    db.commit()
    assert token(client, "gsm-lab-pc", secret).status_code == 401


def test_the_agent_cannot_use_its_secret_in_the_web_app(client, worker):
    _, secret = worker
    r = client.post("/auth/login", json={"username": "gsm-lab-pc", "password": secret})
    assert r.status_code == 401


def test_sign_ins_are_written_to_the_login_log(client, worker, db):
    _, secret = worker
    token(client, "gsm-lab-pc", "wrong")
    token(client, "gsm-lab-pc", secret)
    events = db.execute(text("SELECT event, username, user_id FROM login_log ORDER BY id")).all()
    assert [(e.event, e.username, e.user_id) for e in events] == [
        ("worker_login_failed", "gsm-lab-pc", None),
        ("worker_login", "gsm-lab-pc", None),
    ]


def test_repeated_failures_are_rate_limited(client, worker):
    _, secret = worker
    for _ in range(settings.login_max_failures):
        assert token(client, "gsm-lab-pc", "wrong").status_code == 401
    blocked = token(client, "gsm-lab-pc", secret)  # even the right secret waits
    assert blocked.status_code == 429 and "Retry-After" in blocked.headers


def test_a_worker_token_is_not_a_user_token(client, conn, worker):
    _, secret = worker
    make_login_user(conn, "boss", "admin")
    headers = {"Authorization": f"Bearer {token(client, 'gsm-lab-pc', secret).json()['access_token']}"}
    assert client.get("/auth/me", headers=headers).status_code == 401
    assert client.get("/users", headers=headers).status_code == 401


def test_a_user_token_is_not_a_worker_token(client, conn):
    make_login_user(conn, "boss", "admin")
    r = client.post("/worker/session", headers=auth_header(client, "boss"), json=SESSION)
    assert r.status_code == 401


def test_the_session_needs_a_token(client):
    assert client.post("/worker/session", json=SESSION).status_code == 401


SESSION = {
    "version": "0.1.0",
    "protocol_version": 2,
    "instance_id": "instance-a",
}
