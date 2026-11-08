"""Login rate limiting: repeated failures lock a username (and an address) out for a while."""

import pytest
from sqlalchemy import text

from app.config import settings
from tests.api.conftest import PASSWORD, auth_header, login
from tests.db.helpers import make_login_user

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def small_limits(monkeypatch):
    monkeypatch.setattr(settings, "login_max_failures", 3)
    monkeypatch.setattr(settings, "login_max_failures_per_ip", 6)
    monkeypatch.setattr(settings, "login_lockout_seconds", 600)
    monkeypatch.setattr(settings, "password_max_failures", 3)
    monkeypatch.setattr(settings, "refresh_max_failures_per_ip", 4)


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


# ---- the other sign-in endpoints --------------------------------------------------------------


def change_password(client, headers, current="wrong wrong wrong"):
    return client.put(
        "/auth/me/password",
        headers=headers,
        json={"current_password": current, "new_password": "a brand new passphrase"},
    )


def test_guessing_the_current_password_is_limited(client, alice):
    headers = auth_header(client, "alice")
    assert [change_password(client, headers).status_code for _ in range(3)] == [403, 403, 403]
    blocked = change_password(client, headers)
    assert blocked.status_code == 429 and int(blocked.headers["Retry-After"]) > 0
    # even the right password waits, and the account's sign-in is a separate counter
    assert change_password(client, headers, PASSWORD).status_code == 429
    assert attempt(client, password=PASSWORD).status_code == 200


def test_a_right_current_password_resets_the_password_counter(client, alice):
    headers = auth_header(client, "alice")
    change_password(client, headers)
    change_password(client, headers)
    assert change_password(client, headers, PASSWORD).status_code == 204


def test_password_failures_of_one_user_do_not_block_another(client, alice, conn):
    make_login_user(conn, "bob", "agent")
    headers = auth_header(client, "alice")
    for _ in range(3):
        change_password(client, headers)
    assert change_password(client, auth_header(client, "bob"), PASSWORD).status_code == 204


def test_failed_login_and_failed_password_counters_are_separate(client, alice):
    headers = auth_header(client, "alice")
    for _ in range(2):
        attempt(client)
        change_password(client, headers)
    assert attempt(client).status_code == 401  # the third login failure, not blocked yet
    assert change_password(client, headers).status_code == 403


def test_garbage_refresh_tokens_from_one_address_are_limited(client):
    codes = [
        client.post("/auth/refresh", json={"refresh_token": "junk"}).status_code for _ in range(5)
    ]
    assert codes == [401, 401, 401, 401, 429]


def test_valid_refreshes_are_never_counted(client, alice):
    token = login(client, "alice")["refresh_token"]
    for _ in range(6):
        r = client.post("/auth/refresh", json={"refresh_token": token})
        assert r.status_code == 200
        token = r.json()["refresh_token"]


# ---- admin unlock -------------------------------------------------------------------------------


@pytest.fixture
def admin(client, conn):
    make_login_user(conn, "boss", "admin")
    return auth_header(client, "boss")


def lock(client, name="alice"):
    for _ in range(3):
        attempt(client, name)
    assert attempt(client, name).status_code == 429


def test_users_report_whether_they_are_locked(client, alice, admin):
    def locked():
        items = client.get("/users?page_size=100", headers=admin).json()["items"]
        return {u["username"]: u["locked"] for u in items}

    assert locked()["alice"] is False
    lock(client)
    assert locked() == {"alice": True, "boss": False}


def test_an_admin_can_unlock_a_user(client, alice, admin):
    lock(client)
    r = client.post(f"/users/{alice}/unlock", headers=admin)
    assert r.status_code == 204
    assert attempt(client, password=PASSWORD).status_code == 200


def test_unlock_also_clears_password_guessing(client, alice, admin):
    headers = auth_header(client, "alice")
    for _ in range(3):
        change_password(client, headers)
    assert change_password(client, headers, PASSWORD).status_code == 429
    client.post(f"/users/{alice}/unlock", headers=admin)
    assert change_password(client, headers, PASSWORD).status_code == 204


def test_unlocking_someone_who_is_not_locked_is_fine(client, alice, admin):
    assert client.post(f"/users/{alice}/unlock", headers=admin).status_code == 204


def test_unlock_needs_users_update(client, alice, conn):
    make_login_user(conn, "viewer", "auditor")
    r = client.post(f"/users/{alice}/unlock", headers=auth_header(client, "viewer"))
    assert r.status_code == 403


def test_unlock_of_an_unknown_user_is_404(client, admin):
    assert client.post("/users/999999/unlock", headers=admin).status_code == 404
