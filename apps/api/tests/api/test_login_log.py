"""Login log: its own history of sign-ins, kept apart from the activity log."""

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import ActivityLog, LoginLog
from tests.api.conftest import auth_header, login
from tests.db.helpers import make_login_user

pytestmark = pytest.mark.db


def events(db):
    return [(r.event, r.username, r.user_id) for r in db.scalars(select(LoginLog).order_by(LoginLog.id))]


@pytest.fixture
def boss(conn):
    return make_login_user(conn, "boss", "admin")


def test_a_successful_login_is_recorded_with_the_address(client, db, boss):
    login(client, "boss")
    assert events(db) == [("login", "boss", boss)]
    assert db.scalars(select(LoginLog.ip)).one() == "testclient"


def test_failed_logins_are_recorded_for_real_and_unknown_usernames(client, db, boss):
    client.post("/auth/login", json={"username": "boss", "password": "wrong password!"})
    client.post("/auth/login", json={"username": "ghost", "password": "wrong password!"})
    assert events(db) == [("login_failed", "boss", boss), ("login_failed", "ghost", None)]
    assert "wrong password!" not in str(
        [vars(r) for r in db.scalars(select(LoginLog))]
    )


def test_a_blocked_attempt_is_recorded(client, db, boss, monkeypatch):
    monkeypatch.setattr(settings, "login_max_failures", 2)
    for _ in range(3):
        client.post("/auth/login", json={"username": "boss", "password": "wrong password!"})
    assert [e[0] for e in events(db)] == ["login_failed", "login_failed", "login_blocked"]


def test_logout_is_recorded(client, db, boss):
    tokens = login(client, "boss")
    client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert events(db)[-1] == ("logout", "boss", boss)


def test_a_replayed_refresh_token_is_recorded_as_sessions_ended(client, db, boss):
    tokens = login(client, "boss")
    body = {"refresh_token": tokens["refresh_token"]}
    client.post("/auth/refresh", json=body)
    client.post("/auth/refresh", json=body)  # replay
    assert events(db)[-1] == ("sessions_revoked", "boss", boss)


def test_logins_do_not_go_to_the_activity_log(client, db, boss):
    login(client, "boss")
    assert db.scalars(select(ActivityLog)).all() == []


def test_list_logins_newest_first_with_filters(client, conn, db, boss):
    make_login_user(conn, "viewer", "auditor")
    client.post("/auth/login", json={"username": "ghost", "password": "wrong password!"})
    login(client, "viewer")
    h = auth_header(client, "viewer")
    body = client.get("/logs/logins", headers=h).json()
    assert [(i["event"], i["username"]) for i in body["items"]] == [
        ("login", "viewer"), ("login", "viewer"), ("login_failed", "ghost"),
    ]
    assert body["total"] == 3
    first = body["items"][0]
    assert {"id", "user_id", "ip", "created_at"} <= set(first)

    def total(**params):
        return client.get("/logs/logins", headers=h, params=params).json()["total"]

    assert total(event="login_failed") == 1
    assert total(q="ghost") == 1
    assert total(user_id=conn.exec_driver_sql("SELECT id FROM users WHERE username='viewer'").scalar()) == 2


def test_only_log_readers_may_list(client, conn):
    make_login_user(conn, "op", "operator")
    assert client.get("/logs/logins", headers=auth_header(client, "op")).status_code == 403
