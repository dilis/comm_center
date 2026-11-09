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


def test_ensure_worker_reads_the_secret_from_the_environment(cli_db, monkeypatch, capsys):
    monkeypatch.setenv("WORKER_SECRET", "a-long-enough-secret-value")
    assert cli.main(["ensure-worker", "--name", "local", "--fake-device"]) == 0
    out = capsys.readouterr().out
    assert "a-long-enough-secret-value" not in out  # never echoed
    with cli_db() as db:
        worker = db.query(WorkerAccount).filter_by(name="local").one()
        from app import security

        assert security.verify_password(worker.secret_hash, "a-long-enough-secret-value")
        assert db.query(GsmDevice).filter_by(name="fake", worker_id=worker.id).one()
    assert cli.main(["ensure-worker", "--name", "local", "--fake-device"]) == 0  # idempotent


def test_ensure_worker_needs_the_secret_variable(cli_db, monkeypatch, capsys):
    monkeypatch.delenv("WORKER_SECRET", raising=False)
    assert cli.main(["ensure-worker", "--name", "local"]) == 1
    assert "WORKER_SECRET" in capsys.readouterr().err


def test_assign_device_from_the_command_line(cli_db, capsys):
    cli.main(["create-worker", "--name", "lab-pc"])
    cli.main(["register-device", "--name", "old", "--serial-port", "x", "--phone", "+639170000001"])
    code = cli.main(["assign-device", "--name", "old", "--worker", "lab-pc", "--provider", "fake"])
    assert code == 0
    with cli_db() as db:
        assert db.query(GsmDevice).filter_by(name="old").one().worker_id is not None
    assert cli.main(["assign-device", "--name", "nope", "--worker", "lab-pc"]) == 1
    assert "device" in capsys.readouterr().err


def test_webhook_info_prints_the_url_and_the_devices_key(cli_db, capsys):
    from app import webhooks

    cli.main(["create-worker", "--name", "lab-pc"])
    cli.main([
        "register-device", "--name", "phone1", "--serial-port", "-", "--phone", "+639170000001",
        "--provider", "android", "--worker", "lab-pc",
    ])  # fmt: skip
    capsys.readouterr()
    assert (
        cli.main(["webhook-info", "--name", "phone1", "--base-url", "https://sms.example.com/api"])
        == 0
    )
    out = capsys.readouterr().out
    with cli_db() as db:
        device = db.query(GsmDevice).filter_by(name="phone1").one()
    assert f"https://sms.example.com/api/devices/{device.id}/webhook" in out
    assert webhooks.device_key(device.id) in out
    assert "sms:received" in out and "sms:delivered" in out and "sms:failed" in out


def test_webhook_info_needs_an_android_device(cli_db, capsys):
    cli.main(
        ["register-device", "--name", "plain", "--serial-port", "-", "--phone", "+639170000001"]
    )
    capsys.readouterr()
    assert cli.main(["webhook-info", "--name", "plain", "--base-url", "https://x"]) == 1
    assert "android" in capsys.readouterr().err
    assert cli.main(["webhook-info", "--name", "nope", "--base-url", "https://x"]) == 1
