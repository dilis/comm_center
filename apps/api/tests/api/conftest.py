"""API tests: the real app against the migrated test database, rolled back after each test."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import get_db
from app.main import app
from tests.db.conftest import conn, engine, test_db_url  # noqa: F401 - fixtures

PASSWORD = "correct horse battery"


@pytest.fixture
def db(conn):  # noqa: F811
    # Endpoints commit; savepoints keep those commits inside the test's rolled-back transaction.
    with Session(bind=conn, join_transaction_mode="create_savepoint") as session:
        yield session


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def login(client, username, password=PASSWORD):
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def auth_header(client, username):
    return {"Authorization": f"Bearer {login(client, username)['access_token']}"}
