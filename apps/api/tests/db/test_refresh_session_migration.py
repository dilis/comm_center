"""Migration 0019 keeps the sessions that already exist, each as its own session."""

from sqlalchemy import create_engine, text

from alembic import command
from tests.db.conftest import ADMIN_URL, alembic_config

SCRATCH = "comm_center_sessionfill"
APP_URL = "mysql+pymysql://comm_center:comm_center@127.0.0.1:3307/"


def test_existing_tokens_become_sessions_signed_in_when_they_were_issued():
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {SCRATCH}"))
        c.execute(text(f"CREATE DATABASE {SCRATCH} CHARACTER SET utf8mb4"))
        c.execute(text(f"GRANT ALL ON {SCRATCH}.* TO 'comm_center'@'%'"))
    url = APP_URL + SCRATCH
    cfg = alembic_config(url)
    engine = create_engine(url)
    try:
        command.upgrade(cfg, "0018")
        with engine.begin() as c:
            for jti in ("aaa", "bbb"):
                c.execute(
                    text(
                        "INSERT INTO refresh_token (jti, user_id, expires_at, created_at)"
                        " VALUES (:j, 1, '2036-01-01', '2026-11-01 08:00:00')"
                    ),
                    {"j": jti},
                )
        command.upgrade(cfg, "0019")
        with engine.connect() as c:
            rows = c.execute(
                text(
                    "SELECT jti, session_id, signed_in_at = created_at, ip, user_agent"
                    " FROM refresh_token ORDER BY jti"
                )
            ).all()
        assert [tuple(r) for r in rows] == [
            ("aaa", "aaa", 1, None, None),
            ("bbb", "bbb", 1, None, None),
        ]
    finally:
        engine.dispose()
        with admin.connect() as c:
            c.execute(text(f"DROP DATABASE IF EXISTS {SCRATCH}"))
        admin.dispose()
