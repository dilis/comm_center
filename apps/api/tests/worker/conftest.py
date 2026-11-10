"""Worker tests commit for real (the worker's threads and the API's requests use separate database
sessions that must see each other's rows), so they clean up after themselves instead of relying on a
rolled-back transaction. The worker talks to the real app through FastAPI's test client."""

import pytest
from comm_center_worker.client import ApiClient
from comm_center_worker.fake import FakeProvider
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.db import get_db
from app.devices import register_device
from app.main import app
from tests.db.conftest import engine, test_db_url  # noqa: F401 - fixtures
from tests.db.helpers import insert, make_contact, make_phone

pytestmark = pytest.mark.db

DEVICE_NAME = "d1"
WORKER_NAME = "gsm-d1"  # a worker signs in as its device's agent
WORKER_SECRET = "a-long-enough-worker-secret"


@pytest.fixture
def session_factory(engine):  # noqa: F811
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with engine.connect() as c:
        base_users = c.execute(text("SELECT COALESCE(MAX(id), 0) FROM users")).scalar_one()
        base_contacts = c.execute(text("SELECT COALESCE(MAX(id), 0) FROM contacts")).scalar_one()
    yield factory
    with engine.begin() as c:
        c.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for table in (
            "message_lease",
            "inbound_ref",
            "messages",
            "gsm_device",
            "contact_phone",
            "user_group",
            "login_log",
            "login_attempt",
        ):
            c.execute(text(f"DELETE FROM {table}"))
        c.execute(text("DELETE FROM users WHERE id > :i"), {"i": base_users})
        c.execute(text("DELETE FROM contacts WHERE id > :i"), {"i": base_contacts})
        c.execute(text("SET FOREIGN_KEY_CHECKS = 1"))


@pytest.fixture
def http_app(session_factory):
    """The real app on the test database, each request with its own session that really commits."""

    def get_test_db():
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = get_test_db
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def device(session_factory):
    """The device ``d1`` (agent ``gsm-d1``) and, through it, the worker that serves it."""
    with session_factory() as db:
        return register_device(db, DEVICE_NAME, "+639170000000", secret=WORKER_SECRET)


@pytest.fixture
def make_api(http_app, device):
    """Build an API client for the worker. Each one has its own HTTP client, as each thread of the
    real worker does."""
    made = []

    def build() -> ApiClient:
        api = ApiClient(TestClient(app), WORKER_NAME, WORKER_SECRET)
        made.append(api)
        return api

    yield build
    for api in made:
        api.close()


@pytest.fixture
def api(make_api):
    return make_api()


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
