"""POST /worker/session: the handshake that tells a worker which devices are its own."""

import pytest
from sqlalchemy import text

from app.devices import register_device
from app.worker_accounts import create_worker
from tests.api.test_worker_auth import SESSION

pytestmark = pytest.mark.db


@pytest.fixture
def worker(db):
    row, secret = create_worker(db, "lab-pc")
    db.commit()
    return row, secret


def headers(client, name, secret):
    r = client.post("/worker/token", json={"name": name, "secret": secret})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_the_session_lists_only_the_workers_own_devices(client, db, worker):
    row, secret = worker
    create_worker(db, "other-pc")
    mine = register_device(
        db, "phone1", "http://10.0.0.5:8080", "+639170000001",
        provider="android", config={"base_url": "http://10.0.0.5:8080"}, worker="lab-pc",
    )  # fmt: skip
    register_device(db, "theirs", "x", "+639170000002", worker="other-pc")
    register_device(db, "nobodys", "x", "+639170000003")
    r = client.post("/worker/session", json=SESSION, headers=headers(client, "lab-pc", secret))
    assert r.status_code == 200
    body = r.json()
    assert body["worker_id"] == row.id and body["protocol_version"] == 1
    assert body["devices"] == [
        {
            "id": mine.id, "name": "phone1", "provider": "android",
            "phone_number": "+639170000001", "config": {"base_url": "http://10.0.0.5:8080"},
        }
    ]  # fmt: skip


def test_a_deleted_device_is_not_listed(client, db, worker):
    _, secret = worker
    device = register_device(db, "gone", "x", "+639170000001", worker="lab-pc")
    db.execute(text("UPDATE gsm_device SET deleted_at = NOW() WHERE id = :i"), {"i": device.id})
    db.commit()
    r = client.post("/worker/session", json=SESSION, headers=headers(client, "lab-pc", secret))
    assert r.json()["devices"] == []


def test_the_session_records_what_the_worker_reported(client, db, worker):
    row, secret = worker
    assert row.last_seen_at is None
    client.post(
        "/worker/session",
        json={
            "version": "1.2.3",
            "protocol_version": 1,
            "providers": ["fake", "android"],
            "instance_id": "instance-a",
        },
        headers=headers(client, "lab-pc", secret),
    )
    seen = db.execute(
        text("SELECT version, protocol_version, last_seen_at FROM worker_account WHERE id=:i"),
        {"i": row.id},
    ).one()
    assert seen.version == "1.2.3" and seen.protocol_version == 1 and seen.last_seen_at


def test_an_incompatible_protocol_version_is_refused_clearly(client, worker):
    _, secret = worker
    r = client.post(
        "/worker/session",
        json={**SESSION, "protocol_version": 99},
        headers=headers(client, "lab-pc", secret),
    )
    assert r.status_code == 409
    assert "protocol" in r.json()["detail"] and "1" in r.json()["detail"]


@pytest.mark.parametrize("missing", ["version", "protocol_version", "providers", "instance_id"])
def test_the_report_is_required(client, worker, missing):
    _, secret = worker
    body = {k: v for k, v in SESSION.items() if k != missing}
    r = client.post("/worker/session", json=body, headers=headers(client, "lab-pc", secret))
    assert r.status_code == 422
