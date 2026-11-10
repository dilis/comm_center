"""POST /worker/session: the handshake that tells a worker which device it serves."""

import pytest
from sqlalchemy import text

from app.devices import register_device
from tests.api.test_worker_auth import SESSION
from tests.api.worker_helpers import make_worker_with_device

pytestmark = pytest.mark.db


def test_the_session_names_only_the_workers_own_device(client, db):
    headers, mine = make_worker_with_device(client, db, "phone1", "+639170000001")
    make_worker_with_device(client, db, "theirs", "+639170000002")
    register_device(db, "nobodys", "+639170000003")
    r = client.post("/worker/session", json=SESSION, headers=headers)
    assert r.status_code == 200
    assert r.json() == {
        "protocol_version": 2,
        "devices": [{"id": mine.id, "name": "phone1", "phone_number": "+639170000001"}],
    }


def test_a_deleted_device_cannot_hold_a_session(client, db):
    headers, device = make_worker_with_device(client, db, "gone", "+639170000001")
    db.execute(text("UPDATE gsm_device SET deleted_at = NOW() WHERE id = :i"), {"i": device.id})
    db.commit()
    assert client.post("/worker/session", json=SESSION, headers=headers).status_code == 401


def test_the_session_records_what_the_worker_reported(client, db):
    headers, device = make_worker_with_device(client, db, "lab", "+639170000001")
    assert device.last_seen_at is None
    client.post(
        "/worker/session",
        json={"version": "1.2.3", "protocol_version": 2, "instance_id": "instance-a"},
        headers=headers,
    )
    seen = db.execute(
        text(
            "SELECT version, protocol_version, instance_id, last_seen_at FROM gsm_device "
            "WHERE id=:i"
        ),
        {"i": device.id},
    ).one()
    assert (seen.version, seen.protocol_version, seen.instance_id) == ("1.2.3", 2, "instance-a")
    assert seen.last_seen_at


def test_an_incompatible_protocol_version_is_refused_clearly(client, db):
    headers, _ = make_worker_with_device(client, db)
    r = client.post(
        "/worker/session", json={**SESSION, "protocol_version": 99}, headers=headers
    )
    assert r.status_code == 409
    assert "protocol" in r.json()["detail"] and "2" in r.json()["detail"]


@pytest.mark.parametrize("missing", ["version", "protocol_version", "instance_id"])
def test_the_report_is_required(client, db, missing):
    headers, _ = make_worker_with_device(client, db)
    body = {k: v for k, v in SESSION.items() if k != missing}
    assert client.post("/worker/session", json=body, headers=headers).status_code == 422
