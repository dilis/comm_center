import pytest
from sqlalchemy import text

from app.devices import DeviceError, register_device
from app.messaging import derive_direction


def test_register_device_creates_the_inbound_agent_and_device(session_factory, device):
    with session_factory() as db:
        row = db.execute(
            text("""SELECT d.name, d.serial_port, d.phone_number, d.status, d.owner_id,
                           u.username, u.is_system, u.agent_direction, u.login_enabled,
                           u.password_hash, u.owner_id AS agent_owner, c.type
                    FROM gsm_device d JOIN users u ON u.id = d.agent_user_id
                    JOIN contacts c ON c.id = u.contact_id WHERE d.id = :i"""),
            {"i": device.id},
        ).one()
    assert (row.name, row.serial_port, row.phone_number) == ("d1", "/dev/ttyUSB0", "+639170000000")
    assert row.status == "offline" and row.owner_id == 1 and row.agent_owner == 1
    assert row.username == "gsm-d1" and row.is_system and row.login_enabled == 0
    assert row.password_hash is None and row.type == "entity"
    assert derive_direction(bool(row.is_system), row.agent_direction) == "inbound"


def test_register_device_normalizes_the_number(session_factory):
    with session_factory() as db:
        d = register_device(db, name="d2", serial_port="/dev/ttyUSB1", phone_number="0917 000 0001")
    assert d.phone_number == "+639170000001"


def test_register_device_rejects_bad_input(session_factory, device):
    with session_factory() as db, pytest.raises(DeviceError, match="phone"):
        register_device(db, name="x", serial_port="/dev/x", phone_number="123")
    with session_factory() as db, pytest.raises(DeviceError, match="already"):
        register_device(db, name="d1", serial_port="/dev/y", phone_number="+639170000009")
    with session_factory() as db:
        assert db.execute(text("SELECT COUNT(*) FROM gsm_device")).scalar_one() == 1
