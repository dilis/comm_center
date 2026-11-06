from sqlalchemy import create_engine, inspect, text

from alembic import command
from tests.db.conftest import ADMIN_URL, alembic_config

SCRATCH = "comm_center_roundtrip"
# Migrations must work for the unprivileged application user (as in docker-compose), not just root.
APP_URL = "mysql+pymysql://comm_center:comm_center@127.0.0.1:3307/"


def test_migrations_can_be_downgraded_and_reapplied():
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {SCRATCH}"))
        c.execute(text(f"CREATE DATABASE {SCRATCH} CHARACTER SET utf8mb4"))
        c.execute(text(f"GRANT ALL ON {SCRATCH}.* TO 'comm_center'@'%'"))
    url = APP_URL + SCRATCH
    cfg = alembic_config(url)
    engine = create_engine(url)
    try:
        command.upgrade(cfg, "head")
        assert "users" in inspect(engine).get_table_names()

        command.downgrade(cfg, "base")
        assert inspect(engine).get_table_names() == ["alembic_version"]
        with engine.connect() as c:
            assert c.execute(text("SHOW TRIGGERS")).all() == []

        command.upgrade(cfg, "head")
        with engine.connect() as c:
            assert c.execute(text("SELECT COUNT(*) FROM users")).scalar() == 2
    finally:
        engine.dispose()
        with admin.connect() as c:
            c.execute(text(f"DROP DATABASE IF EXISTS {SCRATCH}"))
        admin.dispose()
