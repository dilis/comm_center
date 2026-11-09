"""The admin commands for workers, run against the real (test) database."""

import pytest
from sqlalchemy.orm import Session

from app import cli
from app.models import GsmDevice, WorkerAccount


@pytest.fixture
def cli_db(conn, monkeypatch):
    """Make the CLI use the rolled-back test connection."""

    def factory():
        return Session(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )  # like SessionLocal

    monkeypatch.setattr(cli, "SessionLocal", factory)
    return factory


def test_create_worker_prints_the_secret_once(cli_db, capsys):
    assert cli.main(["create-worker", "--name", "lab-pc"]) == 0
    out = capsys.readouterr().out
    assert "lab-pc" in out and "secret" in out.lower()
    secret = out.strip().splitlines()[-1].strip()
    with cli_db() as db:
        worker = db.query(WorkerAccount).filter_by(name="lab-pc").one()
        assert secret not in worker.secret_hash and len(secret) >= 32


def test_create_worker_twice_is_an_error(cli_db, capsys):
    assert cli.main(["create-worker", "--name", "lab-pc"]) == 0
    assert cli.main(["create-worker", "--name", "lab-pc"]) == 1
    assert "already exists" in capsys.readouterr().err


def test_register_device_takes_a_provider_config_and_worker(cli_db):
    cli.main(["create-worker", "--name", "lab-pc"])
    code = cli.main([
        "register-device", "--name", "phone1", "--serial-port", "-", "--phone", "+639170000001",
        "--provider", "android", "--config", '{"base_url": "http://10.0.0.5:8080"}',
        "--worker", "lab-pc",
    ])  # fmt: skip
    assert code == 0
    with cli_db() as db:
        device = db.query(GsmDevice).filter_by(name="phone1").one()
        assert device.provider == "android" and device.worker_id is not None
        assert device.config == {"base_url": "http://10.0.0.5:8080"}


def test_register_device_rejects_a_config_that_is_not_a_json_object(cli_db, capsys):
    code = cli.main([
        "register-device", "--name", "p", "--serial-port", "-", "--phone", "+639170000001",
        "--config", "[1]",
    ])  # fmt: skip
    assert code == 1 and "config" in capsys.readouterr().err
