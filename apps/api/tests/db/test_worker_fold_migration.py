"""Migration 0014 folds each worker account into the agent of the device it served."""

from sqlalchemy import create_engine, text

from alembic import command
from tests.db.conftest import ADMIN_URL, alembic_config

SCRATCH = "comm_center_workerfold"
APP_URL = "mysql+pymysql://comm_center:comm_center@127.0.0.1:3307/"


def test_a_workers_secret_and_session_move_to_its_devices_agent_and_back():
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {SCRATCH}"))
        c.execute(text(f"CREATE DATABASE {SCRATCH} CHARACTER SET utf8mb4"))
        c.execute(text(f"GRANT ALL ON {SCRATCH}.* TO 'comm_center'@'%'"))
    url = APP_URL + SCRATCH
    cfg = alembic_config(url)
    engine = create_engine(url)
    try:
        command.upgrade(cfg, "0013")
        with engine.begin() as c:
            c.execute(
                text(
                    "INSERT INTO worker_account (id, name, secret_hash, version, protocol_version,"
                    " instance_id, last_seen_at, owner_id) VALUES"
                    " (10, 'local', 'HASH', '0.1.0', 1, 'inst', '2026-11-10 02:00:00', 1)"
                )
            )
            for i, name in ((20, "a"), (21, "b")):  # one worker that served two devices
                c.execute(
                    text("INSERT INTO contacts (id, first_name, type, owner_id)"
                         " VALUES (:i, :n, 'entity', 1)"),
                    {"i": i, "n": f"gsm-{name}"},
                )
                c.execute(
                    text(
                        "INSERT INTO users (id, contact_id, username, is_system, agent_direction,"
                        " login_enabled, owner_id) VALUES (:i, :i, :n, 1, 'inbound', 0, 1)"
                    ),
                    {"i": i, "n": f"gsm-{name}"},
                )
                c.execute(
                    text(
                        "INSERT INTO gsm_device (id, name, serial_port, phone_number, agent_user_id,"
                        " worker_id, owner_id) VALUES (:i, :n, '/dev/x', '+639170000100', :i, 10, 1)"
                    ),
                    {"i": i, "n": name},
                )
            c.execute(  # a device nobody served keeps no secret
                text("INSERT INTO contacts (id, first_name, type, owner_id) VALUES (22, 'gsm-c', 'entity', 1)")
            )
            c.execute(
                text("INSERT INTO users (id, contact_id, username, is_system, agent_direction,"
                     " login_enabled, owner_id) VALUES (22, 22, 'gsm-c', 1, 'inbound', 0, 1)")
            )
            c.execute(
                text("INSERT INTO gsm_device (id, name, serial_port, phone_number, agent_user_id,"
                     " owner_id) VALUES (22, 'c', '/dev/x', '+639170000100', 22, 1)")
            )

        command.upgrade(cfg, "0014")
        with engine.connect() as c:
            agents = {
                r.username: r.password_hash
                for r in c.execute(text("SELECT username, password_hash FROM users WHERE id >= 20"))
            }
            assert agents == {"gsm-a": "HASH", "gsm-b": "HASH", "gsm-c": None}
            dev = c.execute(
                text("SELECT version, protocol_version, instance_id, last_seen_at FROM gsm_device"
                     " WHERE id = 20")
            ).one()
            assert (dev.version, dev.protocol_version, dev.instance_id) == ("0.1.0", 1, "inst")
            assert str(dev.last_seen_at) == "2026-11-10 02:00:00"
            tables = {r[0] for r in c.execute(text("SHOW TABLES"))}
            assert "worker_account" not in tables

        command.downgrade(cfg, "0013")
        with engine.connect() as c:
            workers = {r.name for r in c.execute(text("SELECT name FROM worker_account"))}
            assert workers == {"gsm-a", "gsm-b"}  # one per device that had a secret
            served = c.execute(text("SELECT COUNT(*) FROM gsm_device WHERE worker_id IS NOT NULL"))
            assert served.scalar_one() == 2
            assert c.execute(
                text("SELECT COUNT(*) FROM users WHERE is_system = 1 AND password_hash IS NOT NULL")
            ).scalar_one() == 0
    finally:
        engine.dispose()
        with admin.connect() as c:
            c.execute(text(f"DROP DATABASE IF EXISTS {SCRATCH}"))
        admin.dispose()
