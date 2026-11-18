"""The notifier (apps/notifier) shares two tables with the API and nothing else. Its contract file
says what they look like; this fails when the API's migrated tables and that file drift apart."""

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from tests.db.conftest import ADMIN_URL, TEST_DB, test_db_url  # noqa: F401 - fixture

pytestmark = pytest.mark.db

CONTRACT = Path(__file__).resolve().parents[2] / "notifier" / "contract" / "outbox.sql"
SCRATCH_DB = "comm_center_contract_check"
TABLES = ("push_subscription", "push_outbox")
COLUMNS = (
    "SELECT table_name, column_name, column_type, is_nullable, column_default, "
    "generation_expression, extra FROM information_schema.columns "
    "WHERE table_schema = :db AND table_name IN ('push_subscription', 'push_outbox') "
    "ORDER BY table_name, ordinal_position"
)
INDEXES = (
    "SELECT table_name, index_name, non_unique, seq_in_index, column_name "
    "FROM information_schema.statistics WHERE table_schema = :db "
    "AND table_name IN ('push_subscription', 'push_outbox') "
    "ORDER BY table_name, index_name, seq_in_index"
)


def describe(conn, db):
    return (
        [tuple(r) for r in conn.execute(text(COLUMNS), {"db": db})],
        [tuple(r) for r in conn.execute(text(INDEXES), {"db": db})],
    )


def test_the_contract_file_matches_the_migrated_tables(test_db_url):  # noqa: F811
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    sql = "\n".join(
        line for line in CONTRACT.read_text().splitlines() if not line.strip().startswith("--")
    )
    try:
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {SCRATCH_DB}"))
            conn.execute(text(f"CREATE DATABASE {SCRATCH_DB} CHARACTER SET utf8mb4"))
        scratch = create_engine(ADMIN_URL + SCRATCH_DB, isolation_level="AUTOCOMMIT")
        with scratch.connect() as conn:
            for statement in sql.split(";"):
                if statement.strip():
                    conn.execute(text(statement))
        with admin.connect() as conn:
            from_contract = describe(conn, SCRATCH_DB)
            from_migrations = describe(conn, TEST_DB)
    finally:
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {SCRATCH_DB}"))
    assert from_contract[0] == from_migrations[0], "columns differ: update apps/notifier/contract/outbox.sql"
    assert from_contract[1] == from_migrations[1], "indexes differ: update apps/notifier/contract/outbox.sql"
    assert {t for t, *_ in from_contract[0]} == set(TABLES)


def test_the_contract_file_exists_where_the_notifier_expects_it():
    assert CONTRACT.is_file(), os.fspath(CONTRACT)
