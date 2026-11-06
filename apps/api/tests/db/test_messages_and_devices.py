import pytest
from sqlalchemy.exc import DBAPIError

from tests.db.helpers import insert, make_contact, make_message, make_user


def test_message_requires_a_contact(conn):
    with pytest.raises(DBAPIError, match="cannot be null"):
        insert(
            conn, "messages", channel="gsm", phone_number="+639171234567", content="x",
            status="queued", owner_id=1, contact_id=None,
        )


def test_message_contact_must_exist(conn):
    with pytest.raises(DBAPIError, match="fk_messages_contact_id"):
        make_message(conn, contact_id=999999)


def test_message_status_must_be_known(conn):
    contact = make_contact(conn)
    for status in ["queued", "sending", "sent", "failed", "delivered", "received"]:
        make_message(conn, contact, status=status)
    with pytest.raises(DBAPIError, match="Data truncated"):
        make_message(conn, contact, status="exploded")


def test_message_phone_snapshot_must_be_e164(conn):
    with pytest.raises(DBAPIError, match="ck_messages_e164"):
        make_message(conn, make_contact(conn), phone_number="0917")


def test_message_channel_must_be_known(conn):
    with pytest.raises(DBAPIError, match="Data truncated"):
        make_message(conn, make_contact(conn), channel="carrier-pigeon")


def _agent(conn, name):
    return make_user(conn, name, is_system=1, agent_direction="inbound", login_enabled=0)


def test_each_gsm_device_has_its_own_agent(conn):
    agent = _agent(conn, "gsm-a")
    insert(conn, "gsm_device", name="A", serial_port="/dev/ttyUSB0", phone_number="+639170000100",
           agent_user_id=agent, owner_id=1)
    with pytest.raises(DBAPIError, match="uq_gsm_device_agent_user_id"):
        insert(conn, "gsm_device", name="B", serial_port="/dev/ttyUSB1",
               phone_number="+639170000101", agent_user_id=agent, owner_id=1)


def test_outbound_message_can_reference_a_device(conn):
    agent = _agent(conn, "gsm-b")
    device = insert(conn, "gsm_device", name="C", serial_port="/dev/ttyUSB2",
                    phone_number="+639170000102", agent_user_id=agent, owner_id=1)
    make_message(conn, make_contact(conn), gsm_device_id=device)
    with pytest.raises(DBAPIError, match="fk_messages_gsm_device_id"):
        make_message(conn, make_contact(conn), gsm_device_id=999999)
