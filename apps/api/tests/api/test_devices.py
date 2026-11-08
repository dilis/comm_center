"""GET /devices: modem health for people who can read every message."""

import pytest
from sqlalchemy import text

from app.devices import register_device
from tests.api.conftest import auth_header
from tests.db.helpers import make_login_user

pytestmark = pytest.mark.db


@pytest.fixture
def modem(db):
    return register_device(db, name="m1", serial_port="/dev/ttyUSB0", phone_number="+639170000000")


def test_lists_devices_with_status_and_last_error(client, conn, db, modem):
    make_login_user(conn, "boss", "admin")
    db.execute(
        text(
            "UPDATE gsm_device SET status='error', last_error='serial port gone', "
            "last_error_at='2026-11-09 08:00:00' WHERE id=:i"
        ),
        {"i": modem.id},
    )
    db.commit()
    r = client.get("/devices", headers=auth_header(client, "boss"))
    assert r.status_code == 200
    assert r.json() == [
        {
            "id": modem.id, "name": "m1", "phone_number": "+639170000000", "status": "error",
            "last_error": "serial port gone", "last_error_at": "2026-11-09T08:00:00",
        }
    ]


def test_a_healthy_device_has_no_error(client, conn, modem):
    make_login_user(conn, "boss", "admin")
    [device] = client.get("/devices", headers=auth_header(client, "boss")).json()
    assert device["status"] == "offline" and device["last_error"] is None


@pytest.mark.parametrize("role,expected", [("admin", 200), ("operator", 200), ("auditor", 200), ("agent", 403)])
def test_only_people_who_read_all_messages_see_devices(client, conn, role, expected):
    make_login_user(conn, "caller", role)
    assert client.get("/devices", headers=auth_header(client, "caller")).status_code == expected


def test_requires_sign_in(client):
    assert client.get("/devices").status_code in (401, 403)
