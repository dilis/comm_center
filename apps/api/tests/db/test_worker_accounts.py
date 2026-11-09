import pytest
from sqlalchemy.orm import Session

from app import security
from app.devices import DeviceError, register_device
from app.worker_accounts import WorkerError, create_worker


@pytest.fixture
def session(conn):
    with Session(bind=conn, join_transaction_mode="create_savepoint") as s:
        yield s


def test_create_worker_returns_the_secret_once_and_stores_only_a_hash(session):
    worker, secret = create_worker(session, "lab-pc")
    assert len(secret) >= 32
    assert worker.secret_hash != secret
    assert security.verify_password(worker.secret_hash, secret)
    assert worker.owner_id == 1


def test_each_worker_gets_a_different_secret(session):
    assert create_worker(session, "a")[1] != create_worker(session, "b")[1]


def test_worker_names_must_be_unique_and_non_blank(session):
    create_worker(session, "lab-pc")
    with pytest.raises(WorkerError, match="already exists"):
        create_worker(session, "lab-pc")
    with pytest.raises(WorkerError, match="name"):
        create_worker(session, "  ")


def test_register_device_with_provider_config_and_worker(session):
    worker, _ = create_worker(session, "lab-pc")
    device = register_device(
        session, "phone1", "http://192.168.1.50:8080", "+639170000001",
        provider="android", config={"base_url": "http://192.168.1.50:8080"}, worker="lab-pc",
    )  # fmt: skip
    assert device.provider == "android"
    assert device.config == {"base_url": "http://192.168.1.50:8080"}
    assert device.worker_id == worker.id


def test_register_device_rejects_an_unknown_worker_or_provider(session):
    with pytest.raises(DeviceError, match="worker"):
        register_device(session, "p", "x", "+639170000001", worker="nobody")
    with pytest.raises(DeviceError, match="provider"):
        register_device(session, "p", "x", "+639170000001", provider="pigeon")


def test_register_device_defaults_stay_as_before(session):
    device = register_device(session, "m1", "/dev/ttyUSB0", "+639170000002")
    assert device.provider == "fake" and device.worker_id is None and device.config == {}


def test_ensure_worker_creates_a_worker_with_the_given_secret(session):
    from app.worker_accounts import ensure_worker

    worker, created = ensure_worker(session, "local", "a-long-enough-secret-value")
    assert created and security.verify_password(worker.secret_hash, "a-long-enough-secret-value")


def test_ensure_worker_again_replaces_the_secret_on_the_same_worker(session):
    from app.worker_accounts import ensure_worker

    first, _ = ensure_worker(session, "local", "a-long-enough-secret-value")
    second, created = ensure_worker(session, "local", "another-long-enough-secret")
    assert not created and second.id == first.id
    assert security.verify_password(second.secret_hash, "another-long-enough-secret")
    assert not security.verify_password(second.secret_hash, "a-long-enough-secret-value")


def test_ensure_worker_refuses_a_short_secret(session):
    from app.worker_accounts import ensure_worker

    with pytest.raises(WorkerError, match="secret"):
        ensure_worker(session, "local", "short")


def test_ensure_fake_device_registers_one_for_the_worker_only_when_there_is_none(session):
    from app.devices import ensure_fake_device
    from app.worker_accounts import ensure_worker

    worker, _ = ensure_worker(session, "local", "a-long-enough-secret-value")
    created = ensure_fake_device(session, "local")
    assert created is not None and created.name == "fake" and created.worker_id == worker.id
    assert created.provider == "fake"
    assert ensure_fake_device(session, "local") is None  # a device already exists


def test_ensure_fake_device_leaves_real_devices_alone(session):
    from app.devices import ensure_fake_device
    from app.worker_accounts import ensure_worker

    ensure_worker(session, "local", "a-long-enough-secret-value")
    register_device(session, "real", "/dev/ttyUSB0", "+639170000002")
    assert ensure_fake_device(session, "local") is None


def test_assign_device_gives_an_existing_device_a_worker_provider_and_config(session):
    from app.devices import assign_device

    worker, _ = create_worker(session, "lab-pc")
    old = register_device(session, "old", "/dev/ttyUSB0", "+639170000003")
    assert old.worker_id is None
    device = assign_device(
        session, "old", "lab-pc", provider="android", config={"base_url": "http://10.0.0.5:8080"}
    )
    assert device.id == old.id and device.worker_id == worker.id
    assert device.provider == "android" and device.config == {"base_url": "http://10.0.0.5:8080"}


def test_assign_device_changes_only_what_it_is_given(session):
    from app.devices import assign_device

    create_worker(session, "a")
    create_worker(session, "b")
    register_device(
        session, "d", "x", "+639170000004", provider="android", config={"k": 1}, worker="a"
    )
    device = assign_device(session, "d", "b")  # only the worker changes
    assert device.provider == "android" and device.config == {"k": 1}


def test_assign_device_rejects_unknown_names(session):
    from app.devices import assign_device

    create_worker(session, "lab-pc")
    register_device(session, "d", "x", "+639170000005")
    with pytest.raises(DeviceError, match="device"):
        assign_device(session, "nope", "lab-pc")
    with pytest.raises(DeviceError, match="worker"):
        assign_device(session, "d", "nobody")
    with pytest.raises(DeviceError, match="provider"):
        assign_device(session, "d", "lab-pc", provider="pigeon")


def test_a_devices_own_number_may_be_in_a_range_the_phone_library_does_not_know_yet(session):
    """The SIM's number is only shown to people, and numbering plans lag behind carriers."""
    device = register_device(session, "newsim", "-", "+639904972662")
    assert device.phone_number == "+639904972662"


def test_a_devices_number_must_still_be_plausible(session):
    for bad in ("123", "+63", "not a number", "+639"):
        with pytest.raises(DeviceError, match="phone"):
            register_device(session, f"bad{abs(hash(bad))}", "-", bad)
