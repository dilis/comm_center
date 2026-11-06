import time

import pytest
from sqlalchemy import text

from app import security
from tests.api.conftest import PASSWORD, auth_header, login
from tests.db.helpers import make_login_user, make_user, soft_delete


@pytest.fixture
def alice(conn):
    return make_login_user(conn, "alice", "agent")


def test_login_returns_token_pair(client, alice):
    body = client.post("/auth/login", json={"username": "alice", "password": PASSWORD}).json()
    assert body["token_type"] == "bearer" and body["expires_in"] > 0
    assert security.decode_token(body["access_token"], "access")["sub"] == str(alice)
    assert security.decode_token(body["refresh_token"], "refresh")["sub"] == str(alice)


@pytest.mark.parametrize("username, password", [("alice", "nope-nope-nope"), ("ghost", PASSWORD)])
def test_bad_credentials_get_the_same_401(client, alice, username, password):
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 401 and r.json() == {"detail": "invalid credentials"}


def test_inactive_user_cannot_log_in(client, conn):
    make_login_user(conn, "dormant", "agent", is_active=0)
    r = client.post("/auth/login", json={"username": "dormant", "password": PASSWORD})
    assert r.status_code == 401


def test_deleted_user_cannot_log_in(client, conn):
    uid = make_login_user(conn, "gone", "agent")
    soft_delete(conn, "users", uid)
    assert client.post("/auth/login", json={"username": "gone", "password": PASSWORD}).status_code == 401


def test_login_disabled_user_cannot_log_in(client, conn):
    make_login_user(conn, "locked", "agent", login_enabled=0)
    assert client.post("/auth/login", json={"username": "locked", "password": PASSWORD}).status_code == 401


@pytest.mark.parametrize("username", ["system", "notification"])
def test_system_agents_cannot_log_in(client, username):
    assert client.post("/auth/login", json={"username": username, "password": ""}).status_code == 401


def test_user_without_password_cannot_log_in(client, conn):
    make_user(conn, "nopass")
    assert client.post("/auth/login", json={"username": "nopass", "password": ""}).status_code == 401


def test_me_requires_a_token(client):
    assert client.get("/auth/me").status_code == 401


def test_me_rejects_a_refresh_token_and_garbage(client, alice):
    refresh = login(client, "alice")["refresh_token"]
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {refresh}"}).status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_me_rejects_expired_access_token(client, alice):
    token, _ = security.create_token(alice, "access", ttl_seconds=-1)
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_me_returns_profile_groups_and_effective_permissions(client, alice):
    body = client.get("/auth/me", headers=auth_header(client, "alice")).json()
    assert body["username"] == "alice" and body["groups"] == ["agent"]
    assert set(body["permissions"]) == {
        "contacts:read_all", "messages:create", "messages:read_own", "messages:read_received",
    }


def test_permission_changes_apply_to_an_existing_token(client, conn, alice):
    headers = auth_header(client, "alice")
    assert "users:read_all" not in client.get("/auth/me", headers=headers).json()["permissions"]
    conn.execute(text(
        "INSERT INTO user_group (user_id, group_id) "
        "SELECT :u, id FROM access_group WHERE name = 'auditor'"), {"u": alice})
    assert "users:read_all" in client.get("/auth/me", headers=headers).json()["permissions"]


def test_deactivated_user_loses_access_with_a_live_token(client, conn, alice):
    headers = auth_header(client, "alice")
    conn.execute(text("UPDATE users SET is_active = 0 WHERE id = :u"), {"u": alice})
    assert client.get("/auth/me", headers=headers).status_code == 401


def test_refresh_rotates_and_spent_token_is_rejected(client, alice):
    first = login(client, "alice")
    second = client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert second.status_code == 200
    assert second.json()["refresh_token"] != first["refresh_token"]
    again = client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert again.status_code == 401


def test_reusing_a_spent_refresh_token_revokes_the_whole_family(client, alice):
    first = login(client, "alice")
    second = client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]}).json()
    client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})  # replay
    r = client.post("/auth/refresh", json={"refresh_token": second["refresh_token"]})
    assert r.status_code == 401


def test_refresh_rejects_access_token_and_unknown_jti(client, alice):
    tokens = login(client, "alice")
    assert client.post("/auth/refresh", json={"refresh_token": tokens["access_token"]}).status_code == 401
    unknown, _ = security.create_token(alice, "refresh", ttl_seconds=60)  # never stored
    assert client.post("/auth/refresh", json={"refresh_token": unknown}).status_code == 401


def test_refresh_fails_after_user_is_deactivated(client, conn, alice):
    tokens = login(client, "alice")
    conn.execute(text("UPDATE users SET is_active = 0 WHERE id = :u"), {"u": alice})
    assert client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401


def test_logout_revokes_the_refresh_token_and_is_idempotent(client, alice):
    tokens = login(client, "alice")
    for _ in range(2):
        assert client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]}).status_code == 204
    assert client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401
    assert client.post("/auth/logout", json={"refresh_token": "junk"}).status_code == 204


def test_expired_refresh_token_is_rejected(client, alice):
    token, _ = security.create_token(alice, "refresh", ttl_seconds=-1)
    assert client.post("/auth/refresh", json={"refresh_token": token}).status_code == 401
    time.sleep(0)  # (expiry is enforced by the JWT itself)
