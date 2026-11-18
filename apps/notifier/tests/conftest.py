"""Database tests run against a throwaway MySQL database built from the contract file, with real
commits (the notifier commits as it works), emptied after every test. Needs MySQL (``pnpm db:up``)."""

import os
from pathlib import Path

import pymysql
import pytest

CONTRACT = Path(__file__).resolve().parents[1] / "contract" / "outbox.sql"
HOST, PORT = "127.0.0.1", int(os.environ.get("TEST_DB_PORT", "3307"))
ROOT_PASSWORD = os.environ.get("TEST_DB_ROOT_PASSWORD", "root")
TEST_DB = "comm_center_notifier_test"


def pytest_collection_modifyitems(items):
    for item in items:
        if "db" in item.fixturenames:
            item.add_marker(pytest.mark.db)


def _connect(database=None, autocommit=True):
    return pymysql.connect(
        host=HOST, port=PORT, user="root", password=ROOT_PASSWORD, database=database,
        autocommit=autocommit, cursorclass=pymysql.cursors.DictCursor,
    )  # fmt: skip


@pytest.fixture(scope="session")
def _schema():
    admin = _connect()
    with admin.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        cur.execute(f"CREATE DATABASE {TEST_DB} CHARACTER SET utf8mb4")
    admin.close()
    conn = _connect(TEST_DB)
    with conn.cursor() as cur:
        sql = "\n".join(
            line for line in CONTRACT.read_text().splitlines() if not line.strip().startswith("--")
        )
        for statement in sql.split(";"):
            if statement.strip():
                cur.execute(statement)
    conn.close()


@pytest.fixture
def connect(_schema):
    """A function that opens a new connection to the test database, as the notifier does."""
    opened = []

    def make():
        conn = _connect(TEST_DB, autocommit=False)
        opened.append(conn)
        return conn

    yield make
    for conn in opened:
        try:
            conn.close()
        except pymysql.err.Error:
            pass  # the notifier closes its own connections
    cleanup = _connect(TEST_DB)
    with cleanup.cursor() as cur:
        cur.execute("DELETE FROM push_outbox")
        cur.execute("DELETE FROM push_subscription")
    cleanup.close()


@pytest.fixture
def db(connect):
    """A connection for the test itself (reads and writes are visible at once)."""
    conn = connect()
    conn.autocommit(True)
    return conn
