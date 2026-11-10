"""The admin commands for devices and their workers, run against the real (test) database."""

import pytest
from sqlalchemy.orm import Session

from app import cli, security
from app.devices import authenticate_device
from app.models import GsmDevice, User


@pytest.fixture
def cli_db(conn, monkeypatch):
    """Make the CLI use the rolled-back test connection."""

    def factory():
        return Session(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )  # like SessionLocal

    monkeypatch.setattr(cli, "SessionLocal", factory)
    return factory


def test_register_device_prints_the_workers_secret_once(cli_db, capsys):
    assert cli.main(["register-device", "--name", "phone1", "--phone", "+639170000001"]) == 0
    out = capsys.readouterr().out
    assert "gsm-phone1" in out and "secret" in out.lower()
    secret = out.strip().splitlines()[-1].strip()
    with cli_db() as db:
        device = db.query(GsmDevice).filter_by(name="phone1").one()
        agent = db.get(User, device.agent_user_id)
        assert secret not in agent.password_hash and len(secret) >= 32
        assert authenticate_device(db, "gsm-phone1", secret).id == device.id


def test_register_device_twice_is_an_error(cli_db, capsys):
    assert cli.main(["register-device", "--name", "phone1", "--phone", "+639170000001"]) == 0
    assert cli.main(["register-device", "--name", "phone1", "--phone", "+639170000002"]) == 1
    assert "already exists" in capsys.readouterr().err


def test_register_device_rejects_a_bad_number(cli_db, capsys):
    assert cli.main(["register-device", "--name", "p", "--phone", "123"]) == 1
    assert "phone" in capsys.readouterr().err


def test_ensure_device_reads_the_secret_from_the_environment(cli_db, monkeypatch, capsys):
    monkeypatch.setenv("WORKER_SECRET", "a-long-enough-secret-value")
    args = ["ensure-device", "--name", "fake", "--phone", "+639170000000"]
    assert cli.main(args) == 0
    out = capsys.readouterr().out
    assert "a-long-enough-secret-value" not in out  # never echoed
    with cli_db() as db:
        device = db.query(GsmDevice).filter_by(name="fake").one()
        agent = db.get(User, device.agent_user_id)
        assert security.verify_password(agent.password_hash, "a-long-enough-secret-value")
    assert cli.main(args) == 0  # idempotent


def test_ensure_device_needs_the_secret_variable(cli_db, monkeypatch, capsys):
    monkeypatch.delenv("WORKER_SECRET", raising=False)
    assert cli.main(["ensure-device", "--name", "fake", "--phone", "+639170000000"]) == 1
    assert "WORKER_SECRET" in capsys.readouterr().err


def test_reset_device_secret_replaces_the_old_one(cli_db, capsys):
    cli.main(["register-device", "--name", "phone1", "--phone", "+639170000001"])
    old = capsys.readouterr().out.strip().splitlines()[-1].strip()
    assert cli.main(["reset-device-secret", "--name", "phone1"]) == 0
    new = capsys.readouterr().out.strip().splitlines()[-1].strip()
    with cli_db() as db:
        assert authenticate_device(db, "gsm-phone1", new) is not None
        assert authenticate_device(db, "gsm-phone1", old) is None
    assert cli.main(["reset-device-secret", "--name", "nope"]) == 1
    assert "device" in capsys.readouterr().err


def test_webhook_info_prints_the_url_and_the_devices_key(cli_db, capsys):
    from app import webhooks

    cli.main(["register-device", "--name", "phone1", "--phone", "+639170000001"])
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


def test_webhook_info_for_an_unknown_device_is_an_error(cli_db, capsys):
    assert cli.main(["webhook-info", "--name", "nope", "--base-url", "https://x"]) == 1
    assert "unknown device" in capsys.readouterr().err
