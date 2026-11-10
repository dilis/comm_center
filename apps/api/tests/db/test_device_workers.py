"""A worker is the device's agent: registering a device, its secret and signing in."""

import pytest
from sqlalchemy.orm import Session

from app import security
from app.devices import (
    DeviceError,
    authenticate_device,
    ensure_device,
    register_device,
    set_device_secret,
)
from app.models import User


@pytest.fixture
def session(conn):
    with Session(bind=conn, join_transaction_mode="create_savepoint") as s:
        yield s


def agent_of(session, device):
    return session.get(User, device.agent_user_id)


def test_register_device_creates_its_inbound_agent(session):
    device = register_device(session, "phone1", "+639170000001")
    agent = agent_of(session, device)
    assert agent.username == "gsm-phone1" and agent.is_system and agent.agent_direction == "inbound"
    assert agent.login_enabled is False and agent.password_hash is None  # no secret yet


def test_register_device_with_a_secret_stores_only_a_hash(session):
    device = register_device(session, "phone1", "+639170000001", secret="a-long-enough-secret-value")
    hash_ = agent_of(session, device).password_hash
    assert hash_ != "a-long-enough-secret-value"
    assert security.verify_password(hash_, "a-long-enough-secret-value")


def test_register_device_rejects_a_duplicate_name_and_a_bad_number(session):
    register_device(session, "m1", "+639170000002")
    with pytest.raises(DeviceError, match="already exists"):
        register_device(session, "m1", "+639170000003")
    with pytest.raises(DeviceError, match="name"):
        register_device(session, "  ", "+639170000003")
    with pytest.raises(DeviceError, match="secret"):
        register_device(session, "m2", "+639170000003", secret="short")


def test_set_device_secret_returns_a_new_one_and_replaces_the_old(session):
    register_device(session, "m1", "+639170000002", secret="a-long-enough-secret-value")
    first = set_device_secret(session, "m1")
    assert len(first) >= 32 and set_device_secret(session, "m1") != first
    assert authenticate_device(session, "gsm-m1", "a-long-enough-secret-value") is None


def test_set_device_secret_for_an_unknown_device_is_an_error(session):
    with pytest.raises(DeviceError, match="unknown device"):
        set_device_secret(session, "nope")


def test_authenticate_device_needs_the_agents_username_and_secret(session):
    device = register_device(session, "m1", "+639170000002")
    secret = set_device_secret(session, "m1")
    assert authenticate_device(session, "gsm-m1", secret).id == device.id
    assert authenticate_device(session, "gsm-m1", "wrong") is None
    assert authenticate_device(session, "m1", secret) is None  # the device name is not the login
    assert authenticate_device(session, "gsm-nope", secret) is None


def test_authenticate_device_refuses_other_users(session):
    """Only a device's agent is a worker: not the system user, not a human with a password."""
    assert authenticate_device(session, "system", "anything") is None
    register_device(session, "m1", "+639170000002")  # an agent with no secret at all
    assert authenticate_device(session, "gsm-m1", "") is None


def test_ensure_device_creates_with_the_given_secret(session):
    device, created = ensure_device(session, "fake", "+639170000000", "a-long-enough-secret-value")
    assert created and authenticate_device(session, "gsm-fake", "a-long-enough-secret-value")
    assert device.name == "fake"


def test_ensure_device_again_replaces_the_secret_on_the_same_device(session):
    first, _ = ensure_device(session, "fake", "+639170000000", "a-long-enough-secret-value")
    second, created = ensure_device(session, "fake", "+639170000000", "another-long-enough-secret")
    assert not created and second.id == first.id
    assert authenticate_device(session, "gsm-fake", "another-long-enough-secret")
    assert authenticate_device(session, "gsm-fake", "a-long-enough-secret-value") is None


def test_ensure_device_refuses_a_short_secret(session):
    with pytest.raises(DeviceError, match="secret"):
        ensure_device(session, "fake", "+639170000000", "short")


def test_a_devices_own_number_may_be_in_a_range_the_phone_library_does_not_know_yet(session):
    """The SIM's number is only shown to people, and numbering plans lag behind carriers."""
    assert register_device(session, "newsim", "+639904972662").phone_number == "+639904972662"


def test_a_devices_number_must_still_be_plausible(session):
    for bad in ("123", "+63", "not a number", "+639"):
        with pytest.raises(DeviceError, match="phone"):
            register_device(session, f"bad{abs(hash(bad))}", bad)
