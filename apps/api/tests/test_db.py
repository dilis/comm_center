import pytest
from sqlalchemy import text

from app.db import engine

pytestmark = pytest.mark.db


def test_mysql_connection_works():
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1


def test_database_is_mysql_8():
    with engine.connect() as conn:
        version = conn.execute(text("SELECT VERSION()")).scalar()
    assert version.startswith("8.")
