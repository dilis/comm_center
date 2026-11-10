"""A worker is its device's agent: the schema keeps no worker table, and the session a worker
reports lives on the device."""

from sqlalchemy import inspect, text

from tests.db.helpers import insert, make_user


def make_device(conn, name="d1", **cols) -> int:
    agent = make_user(conn, f"gsm-{name}", is_system=1, agent_direction="inbound", login_enabled=0)
    return insert(
        conn, "gsm_device", name=name, phone_number="+639170000100", agent_user_id=agent,
        owner_id=1, **cols,
    )  # fmt: skip


def test_there_is_no_worker_account_table(conn):
    assert "worker_account" not in inspect(conn).get_table_names()


def test_a_device_keeps_no_how_to_reach_it(conn):
    columns = {c["name"] for c in inspect(conn).get_columns("gsm_device")}
    assert not columns & {"serial_port", "provider", "config", "worker_id"}


def test_a_lease_belongs_to_a_device_not_a_worker(conn):
    columns = {c["name"] for c in inspect(conn).get_columns("message_lease")}
    assert "worker_id" not in columns and "device_id" in columns


def test_the_session_columns_start_empty(conn):
    device = make_device(conn)
    row = conn.execute(
        text(
            "SELECT version, protocol_version, instance_id, last_seen_at FROM gsm_device "
            "WHERE id=:i"
        ),
        {"i": device},
    ).one()
    assert tuple(row) == (None, None, None, None)
