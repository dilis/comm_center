"""Worker accounts and the device columns that tie a device to a worker and a provider."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.db.helpers import insert, make_user


def make_worker(conn, name="w1", **cols) -> int:
    cols.setdefault("secret_hash", "x")
    return insert(conn, "worker_account", name=name, owner_id=1, **cols)


def make_device(conn, name="d1", **cols) -> int:
    agent = make_user(conn, f"gsm-{name}", is_system=1, agent_direction="inbound", login_enabled=0)
    return insert(
        conn, "gsm_device", name=name, serial_port="x", phone_number="+639170000100",
        agent_user_id=agent, owner_id=1, **cols,
    )  # fmt: skip


def test_a_worker_name_is_unique(conn):
    make_worker(conn, "w1")
    with pytest.raises(DBAPIError, match="uq_worker_account_name"):
        make_worker(conn, "w1")


def test_a_worker_needs_a_secret(conn):
    with pytest.raises(DBAPIError, match="secret_hash"):
        insert(conn, "worker_account", name="w2", owner_id=1)


def test_a_device_defaults_to_the_fake_provider_with_no_worker_or_config(conn):
    device = make_device(conn)
    row = conn.execute(
        text("SELECT provider, config, worker_id FROM gsm_device WHERE id=:i"), {"i": device}
    ).one()
    assert row.provider == "fake" and row.worker_id is None
    assert row.config in ("{}", {})


@pytest.mark.parametrize("provider", ["fake", "android", "gsm_modem"])
def test_the_three_providers_are_accepted(conn, provider):
    make_device(conn, provider=provider)


def test_an_unknown_provider_is_rejected(conn):
    with pytest.raises(DBAPIError, match="provider"):
        make_device(conn, provider="carrier_pigeon")


def test_a_device_can_only_belong_to_an_existing_worker(conn):
    make_device(conn, "ok", worker_id=make_worker(conn))
    with pytest.raises(DBAPIError, match="fk_gsm_device_worker_id"):
        make_device(conn, "bad", worker_id=999999)
