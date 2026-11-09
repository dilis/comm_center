"""A worker signs in with its name and secret and gets a short-lived worker token."""

import pytest
from sqlalchemy import text

from app import security
from app.config import settings
from app.worker_accounts import create_worker
from tests.api.conftest import auth_header
from tests.db.helpers import make_login_user

pytestmark = pytest.mark.db


@pytest.fixture
def worker(db):
    row, secret = create_worker(db, "lab-pc")
    db.commit()
    return row, secret


def token(client, name, secret):
    return client.post("/worker/token", json={"name": name, "secret": secret})


def test_valid_credentials_give_a_worker_token(client, worker):
    _, secret = worker
    r = token(client, "lab-pc", secret)
    assert r.status_code == 200
    body = r.json()
    assert (
        body["token_type"] == "bearer" and body["expires_in"] == settings.worker_token_ttl_seconds
    )
    claims = security.decode_token(body["access_token"], "worker")
    assert claims["sub"] == str(worker[0].id)


@pytest.mark.parametrize("name,secret", [("lab-pc", "wrong"), ("nobody", "whatever")])
def test_bad_credentials_are_refused_the_same_way(client, worker, name, secret):
    r = token(client, name, secret)
    assert r.status_code == 401 and r.json() == {"detail": "invalid credentials"}


def test_a_deleted_worker_cannot_sign_in(client, worker, db):
    row, secret = worker
    db.execute(text("UPDATE worker_account SET deleted_at = NOW() WHERE id = :i"), {"i": row.id})
    db.commit()
    assert token(client, "lab-pc", secret).status_code == 401


def test_sign_ins_are_written_to_the_login_log(client, worker, db):
    _, secret = worker
    token(client, "lab-pc", "wrong")
    token(client, "lab-pc", secret)
    events = db.execute(text("SELECT event, username, user_id FROM login_log ORDER BY id")).all()
    assert [(e.event, e.username, e.user_id) for e in events] == [
        ("worker_login_failed", "lab-pc", None),
        ("worker_login", "lab-pc", None),
    ]


def test_repeated_failures_are_rate_limited(client, worker):
    _, secret = worker
    for _ in range(settings.login_max_failures):
        assert token(client, "lab-pc", "wrong").status_code == 401
    blocked = token(client, "lab-pc", secret)  # even the right secret waits
    assert blocked.status_code == 429 and "Retry-After" in blocked.headers


def test_a_worker_token_is_not_a_user_token(client, conn, worker):
    _, secret = worker
    make_login_user(conn, "boss", "admin")
    headers = {"Authorization": f"Bearer {token(client, 'lab-pc', secret).json()['access_token']}"}
    assert client.get("/auth/me", headers=headers).status_code == 401
    assert client.get("/users", headers=headers).status_code == 401


def test_a_user_token_is_not_a_worker_token(client, conn):
    make_login_user(conn, "boss", "admin")
    r = client.post("/worker/session", headers=auth_header(client, "boss"), json=SESSION)
    assert r.status_code == 401


def test_the_session_needs_a_token(client):
    assert client.post("/worker/session", json=SESSION).status_code == 401


SESSION = {"version": "0.1.0", "protocol_version": 1, "providers": ["fake"]}
