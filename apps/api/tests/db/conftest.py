"""Database test harness.

Builds a throwaway MySQL database by running the real Alembic migrations, then gives each test a
connection inside a transaction that is rolled back afterwards. Requires MySQL (``pnpm db:up``).
"""

import os
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text

from alembic import command

API_DIR = Path(__file__).resolve().parents[2]
ADMIN_URL = os.environ.get(
    "TEST_DATABASE_ADMIN_URL", "mysql+pymysql://root:root@127.0.0.1:3307/"
)
TEST_DB = "comm_center_test"


def pytest_collection_modifyitems(items):
    for item in items:
        if "tests/db/" in str(item.fspath) or "tests/api/" in str(item.fspath):
            item.add_marker(pytest.mark.db)


def alembic_config(url: str) -> Config:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture(scope="session")
def test_db_url() -> str:
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB}"))
        conn.execute(text(f"CREATE DATABASE {TEST_DB} CHARACTER SET utf8mb4"))
    admin.dispose()
    url = ADMIN_URL + TEST_DB
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture(scope="session")
def engine(test_db_url):
    eng = create_engine(test_db_url)
    yield eng
    eng.dispose()


@pytest.fixture
def conn(engine):
    """A connection inside a transaction that is always rolled back."""
    with engine.connect() as connection:
        trans = connection.begin()
        try:
            yield connection
        finally:
            trans.rollback()
