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
