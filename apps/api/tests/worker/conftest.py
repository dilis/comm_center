"""Worker tests commit for real (several connections must see each other's rows), so they clean up
after themselves instead of relying on a rolled-back transaction."""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.devices import register_device
from app.worker.fake import FakeProvider
from tests.db.conftest import engine, test_db_url  # noqa: F401 - fixtures
from tests.db.helpers import insert, make_contact, make_phone

pytestmark = pytest.mark.db


@pytest.fixture
def session_factory(engine):  # noqa: F811
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with engine.connect() as c:
        base_users = c.execute(text("SELECT COALESCE(MAX(id), 0) FROM users")).scalar_one()
        base_contacts = c.execute(text("SELECT COALESCE(MAX(id), 0) FROM contacts")).scalar_one()
    yield factory
    with engine.begin() as c:
        c.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for table in ("messages", "gsm_device", "contact_phone", "user_group"):
            c.execute(text(f"DELETE FROM {table}"))
        c.execute(text("DELETE FROM users WHERE id > :i"), {"i": base_users})
        c.execute(text("DELETE FROM contacts WHERE id > :i"), {"i": base_contacts})
        c.execute(text("SET FOREIGN_KEY_CHECKS = 1"))


@pytest.fixture
def device(session_factory):
    with session_factory() as db:
        return register_device(
            db, name="d1", serial_port="/dev/ttyUSB0", phone_number="+639170000000"
        )


@pytest.fixture
def provider():
    return FakeProvider()


@pytest.fixture
def sleeps():
    return []


@pytest.fixture
def sleep(sleeps):
    return sleeps.append


@pytest.fixture
def commit(session_factory):
    """Insert rows with real commits: ``commit(make_contact, 'Ana')``."""

    def run(fn, *args, **kwargs):
        with session_factory() as db:
            conn = db.connection()
            result = fn(conn, *args, **kwargs)
            db.commit()
            return result

    return run


@pytest.fixture
def ana(commit):
    cid = commit(make_contact, "Ana")
    commit(make_phone, cid, "+639171234567", is_primary=1)
    return cid


def queue(commit, contact_id, content="hello", **cols):
    from tests.db.helpers import make_message

    cols.setdefault("phone_number", "+639171234567")
    return commit(
        make_message, contact_id, owner_id=cols.pop("owner_id", 1), content=content, **cols
    )


def row(session_factory, message_id):
    with session_factory() as db:
        return db.execute(
            text(
                "SELECT status, sent_at, error_message, gsm_device_id, deleted_at "
                "FROM messages WHERE id=:i"
            ),
            {"i": message_id},
        ).one()


__all__ = ["insert", "queue", "row"]
