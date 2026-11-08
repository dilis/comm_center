"""Login rate limiting: repeated failures lock a username (and an address) out for a while."""

import pytest
from sqlalchemy import text

from app.config import settings
from tests.api.conftest import PASSWORD
from tests.db.helpers import make_login_user

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def small_limits(monkeypatch):
    monkeypatch.setattr(settings, "login_max_failures", 3)
    monkeypatch.setattr(settings, "login_max_failures_per_ip", 6)
    monkeypatch.setattr(settings, "login_lockout_seconds", 600)


@pytest.fixture
def alice(conn):
    return make_login_user(conn, "alice", "agent")


def attempt(client, username="alice", password="wrong password"):
    return client.post("/auth/login", json={"username": username, "password": password})


def test_repeated_failures_lock_the_username_out(client, alice):
    assert [attempt(client).status_code for _ in range(3)] == [401, 401, 401]
    locked = attempt(client)
    assert locked.status_code == 429
    assert 0 < int(locked.headers["Retry-After"]) <= 600


def test_the_right_password_does_not_get_in_while_locked(client, alice):
    for _ in range(3):
        attempt(client)
    assert attempt(client, password=PASSWORD).status_code == 429


def test_lockout_ends_when_the_failures_age_out(client, alice, conn):
    for _ in range(3):
        attempt(client)
    conn.execute(text("UPDATE login_attempt SET created_at = created_at - INTERVAL 11 MINUTE"))
    assert attempt(client, password=PASSWORD).status_code == 200


def test_a_successful_login_forgets_earlier_failures(client, alice):
    attempt(client)
    attempt(client)
    assert attempt(client, password=PASSWORD).status_code == 200
    assert [attempt(client).status_code for _ in range(3)] == [401, 401, 401]


def test_unknown_usernames_are_limited_the_same_way(client):
    assert [attempt(client, "nobody").status_code for _ in range(3)] == [401, 401, 401]
    assert attempt(client, "nobody").status_code == 429


def test_username_matching_ignores_case_and_spaces(client, alice):
    for name in ("alice", "ALICE", " Alice "):
        attempt(client, name)
    assert attempt(client, "alice").status_code == 429


def test_one_locked_username_does_not_lock_others(client, alice, conn):
    make_login_user(conn, "bob", "agent")
    for _ in range(3):
        attempt(client)
    assert attempt(client, "bob", PASSWORD).status_code == 200


def test_one_address_trying_many_usernames_is_limited(client, conn):
    codes = [attempt(client, f"user{i}").status_code for i in range(7)]
    assert codes == [401] * 6 + [429]


def test_blocked_attempts_do_not_extend_the_lockout(client, alice, conn):
    for _ in range(3):
        attempt(client)
    for _ in range(5):
        attempt(client)
    n = conn.execute(text("SELECT COUNT(*) FROM login_attempt")).scalar_one()
    assert n == 3
