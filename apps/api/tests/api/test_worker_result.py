"""Reporting what happened to a claimed message, and keeping its lease alive meanwhile."""

import pytest
from sqlalchemy import text

from app.config import settings
from app.devices import register_device
from tests.api.worker_helpers import (
    PHONE,
    lease_row,
    make_worker_with_device,
    message_row,
    other_worker,
)
from tests.db.helpers import make_contact, make_message, make_phone

pytestmark = pytest.mark.db


@pytest.fixture
def held(client, conn, db):
    """A message claimed by worker w1: (headers, device, message_id)."""
    headers, device = make_worker_with_device(client, db)
    cid = make_contact(conn, "Ana")
    make_phone(conn, cid, PHONE, is_primary=1)
    mid = make_message(conn, cid)
    db.commit()
    assert (
        client.post("/worker/claim", json={"device_id": device.id}, headers=headers).json()[
            "message"
        ]["id"]
        == mid
    )
    return headers, device, mid


def result(client, headers, mid, **body):
    return client.post(f"/worker/messages/{mid}/result", json=body, headers=headers)


def test_sent_records_the_time_and_releases_the_lease(client, db, held):
    headers, _, mid = held
    assert result(client, headers, mid, status="sent").status_code == 204
    row = message_row(db, mid)
    assert row.status == "sent" and row.sent_at is not None and row.error_message is None
    assert lease_row(db, mid) is None


def test_failed_records_the_error(client, db, held):
    headers, _, mid = held
    assert result(client, headers, mid, status="failed", error="no signal").status_code == 204
    row = message_row(db, mid)
    assert (row.status, row.error_message, row.sent_at) == ("failed", "no signal", None)


def test_a_long_error_is_cut_to_fit(client, db, held):
    headers, _, mid = held
    result(client, headers, mid, status="failed", error="x" * 5000)
    assert len(message_row(db, mid).error_message) == 1000


def test_it_also_reaches_a_message_deleted_while_it_was_sending(client, db, held):
    headers, _, mid = held
    db.execute(text("UPDATE messages SET deleted_at = NOW() WHERE id = :i"), {"i": mid})
    assert result(client, headers, mid, status="sent").status_code == 204
    assert message_row(db, mid).status == "sent"


def test_a_late_result_is_still_accepted_until_the_lease_is_reaped(client, db, held):
    headers, _, mid = held
    db.execute(
        text(
            "UPDATE message_lease SET expires_at = UTC_TIMESTAMP() - INTERVAL 5 SECOND WHERE message_id=:i"
        ),
        {"i": mid},
    )
    assert result(client, headers, mid, status="sent").status_code == 204


def test_a_second_result_is_a_conflict(client, held):
    headers, _, mid = held
    result(client, headers, mid, status="sent")
    assert result(client, headers, mid, status="failed", error="x").status_code == 409


def test_another_worker_cannot_report_it(client, db, held):
    _, _, mid = held
    other, _ = other_worker(client, db)
    assert result(client, other, mid, status="sent").status_code == 409


def test_an_unleased_or_unknown_message_is_a_conflict(client, conn, db, held):
    headers, _, _ = held
    cid = make_contact(conn, "Bo")
    queued = make_message(conn, cid)
    assert result(client, headers, queued, status="sent").status_code == 409
    assert result(client, headers, 999999, status="sent").status_code == 409


@pytest.mark.parametrize("status", ["delivered", "queued", "sending", ""])
def test_only_sent_or_failed_can_be_reported(client, held, status):
    headers, _, mid = held
    assert result(client, headers, mid, status=status).status_code == 422


def test_extend_pushes_the_lease_forward(client, db, held):
    headers, _, mid = held
    db.execute(
        text(
            "UPDATE message_lease SET expires_at = UTC_TIMESTAMP() + INTERVAL 5 SECOND WHERE message_id=:i"
        ),
        {"i": mid},
    )
    r = client.post(f"/worker/messages/{mid}/extend", headers=headers)
    assert r.status_code == 200 and r.json()["lease_seconds"] == settings.worker_lease_seconds
    seconds = db.execute(
        text(
            "SELECT TIMESTAMPDIFF(SECOND, UTC_TIMESTAMP(), expires_at) FROM message_lease WHERE message_id=:i"
        ),
        {"i": mid},
    ).scalar_one()
    assert seconds > settings.worker_lease_seconds - 5


def test_extend_needs_a_lease_this_worker_holds(client, db, held):
    headers, _, mid = held
    other, _ = other_worker(client, db)
    assert client.post(f"/worker/messages/{mid}/extend", headers=other).status_code == 409
    result(client, headers, mid, status="sent")
    assert client.post(f"/worker/messages/{mid}/extend", headers=headers).status_code == 409


def test_the_requests_need_a_worker_token(client, held):
    _, _, mid = held
    assert client.post(f"/worker/messages/{mid}/result", json={"status": "sent"}).status_code == 401
    assert client.post(f"/worker/messages/{mid}/extend").status_code == 401


__all__ = ["register_device"]


def test_a_sent_report_does_not_undo_a_delivery_that_already_arrived(client, db, held):
    """The phone's delivered webhook can beat the worker's own report."""
    headers, _, mid = held
    db.execute(text("UPDATE messages SET status='delivered' WHERE id=:i"), {"i": mid})
    assert result(client, headers, mid, status="sent").status_code == 204
    assert message_row(db, mid).status == "delivered"
    assert lease_row(db, mid) is None  # the lease is still released


def test_a_sent_report_does_not_undo_a_failure_the_phone_already_reported(client, db, held):
    headers, _, mid = held
    db.execute(
        text("UPDATE messages SET status='failed', error_message='no SIM' WHERE id=:i"), {"i": mid}
    )
    result(client, headers, mid, status="sent")
    row = message_row(db, mid)
    assert (row.status, row.error_message) == ("failed", "no SIM")
