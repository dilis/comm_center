"""Sessions: one per sign-in, carried across refresh token rotation. Listed for yourself on
``/auth/me/sessions`` and for everyone on ``/logs/sessions``."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app import push
from app.clock import utcnow
from app.config import settings
from app.models import ActivityLog, LoginLog, PushSubscription, RefreshToken, User
from tests.api.conftest import PASSWORD, login
from tests.db.helpers import make_login_user

pytestmark = pytest.mark.db

PHONE = "Mozilla/5.0 (Linux; Android 14) Chrome/130.0 Mobile Safari/537.36"
LAPTOP = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Version/17.0 Safari/605.1.15"


def sign_in(client, username, agent=LAPTOP):
    response = client.post(
        "/auth/login",
        json={"username": username, "password": PASSWORD},
        headers={"User-Agent": agent},
    )
    assert response.status_code == 200, response.text
    return response.json()


def bearer(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def refresh(client, tokens, agent=LAPTOP):
    response = client.post(
        "/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
        headers={"User-Agent": agent},
    )
    assert response.status_code == 200, response.text
    return response.json()


def mine(client, tokens, **params):
    response = client.get("/auth/me/sessions", headers=bearer(tokens), params=params)
    assert response.status_code == 200, response.text
    return response.json()


def everyone(client, tokens, **params):
    response = client.get("/logs/sessions", headers=bearer(tokens), params=params)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def boss(conn):
    return make_login_user(conn, "boss", "admin")


def test_each_sign_in_is_a_session_and_the_callers_own_is_marked(client, boss):
    phone = sign_in(client, "boss", PHONE)
    laptop = sign_in(client, "boss", LAPTOP)
    body = mine(client, laptop)
    assert body["total"] == 2
    assert {(s["user_agent"], s["current"]) for s in body["items"]} == {
        (PHONE, False),
        (LAPTOP, True),
    }
    assert {s["ip"] for s in body["items"]} == {"testclient"}
    assert {"id", "signed_in_at", "last_active_at"} <= set(body["items"][0])
    assert [s["current"] for s in mine(client, phone)["items"] if s["user_agent"] == PHONE] == [True]


def test_a_refresh_continues_the_same_session(client, db, boss):
    tokens = sign_in(client, "boss", PHONE)
    first = db.scalars(select(RefreshToken)).one()
    first.signed_in_at = first.created_at = utcnow().replace(microsecond=0) - timedelta(days=3)
    db.commit()
    before = mine(client, tokens)["items"][0]
    after = mine(client, refresh(client, tokens, LAPTOP))
    assert after["total"] == 1
    session = after["items"][0]
    assert session["id"] == before["id"]
    assert session["current"] is True
    assert session["signed_in_at"] == before["signed_in_at"]
    assert session["last_active_at"] > before["last_active_at"]
    assert session["user_agent"] == LAPTOP  # what it was last seen as


def test_signed_out_and_expired_sessions_are_not_listed(client, db, boss):
    gone = sign_in(client, "boss", PHONE)
    sign_in(client, "boss", "expired")
    here = sign_in(client, "boss")
    client.post("/auth/logout", json={"refresh_token": gone["refresh_token"]})
    row = db.scalars(select(RefreshToken).where(RefreshToken.user_agent == "expired")).one()
    row.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert [s["user_agent"] for s in mine(client, here)["items"]] == [LAPTOP]


def test_my_sessions_never_include_another_persons(client, conn, boss):
    make_login_user(conn, "op", "operator")
    sign_in(client, "boss", PHONE)
    tokens = sign_in(client, "op")
    assert mine(client, tokens)["total"] == 1


def test_a_long_user_agent_is_cut_to_fit(client, boss):
    tokens = sign_in(client, "boss", "x" * 600)
    assert mine(client, tokens)["items"][0]["user_agent"] == "x" * 255


def test_my_sessions_need_a_sign_in(client):
    assert client.get("/auth/me/sessions").status_code == 401


def test_log_readers_see_who_is_signed_in(client, conn, boss):
    op = make_login_user(conn, "op", "operator")
    sign_in(client, "op", PHONE)
    admin = sign_in(client, "boss")
    body = everyone(client, admin)
    assert body["total"] == 2
    row = next(s for s in body["items"] if s["username"] == "op")
    assert row["user_id"] == op
    assert row["name"]
    assert row["user_agent"] == PHONE
    assert everyone(client, admin, q="op")["total"] == 1
    assert everyone(client, admin, q="testcli")["total"] == 2
    page = everyone(client, admin, page_size=1, page=2)
    assert (page["total"], len(page["items"])) == (2, 1)


@pytest.mark.parametrize("change", ["is_active", "deleted_at"])
def test_people_who_can_no_longer_sign_in_are_not_listed(client, db, conn, boss, change):
    op = make_login_user(conn, "op", "operator")
    sign_in(client, "op")
    admin = sign_in(client, "boss")
    user = db.get(User, op)
    setattr(user, change, False if change == "is_active" else utcnow())
    db.commit()
    assert [s["username"] for s in everyone(client, admin)["items"]] == ["boss"]


def test_only_log_readers_see_everyones_sessions(client, conn):
    make_login_user(conn, "op", "operator")
    tokens = login(client, "op")
    assert client.get("/logs/sessions", headers=bearer(tokens)).status_code == 403


# --- signing a session out ------------------------------------------------------------------


def try_refresh(client, tokens):
    return client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})


def id_of(client, tokens):
    return next(s["id"] for s in mine(client, tokens)["items"] if s["current"])


def end_mine(client, tokens, session_id):
    return client.delete(f"/auth/me/sessions/{session_id}", headers=bearer(tokens))


def end_theirs(client, tokens, user_id, session_id):
    return client.delete(f"/users/{user_id}/sessions/{session_id}", headers=bearer(tokens))


def test_signing_out_one_of_your_sessions_leaves_the_others(client, db, boss):
    phone = sign_in(client, "boss", PHONE)
    laptop = sign_in(client, "boss")
    target = id_of(client, phone)
    assert end_mine(client, laptop, target).status_code == 204
    assert [s["current"] for s in mine(client, laptop)["items"]] == [True]
    # the signed-out device trying again is refused, and costs nobody else their session
    assert try_refresh(client, phone).status_code == 401
    assert try_refresh(client, laptop).status_code == 200
    assert "sessions_revoked" not in db.scalars(select(LoginLog.event)).all()


def test_a_session_can_be_signed_out_after_it_has_refreshed(client, boss):
    phone = refresh(client, sign_in(client, "boss", PHONE), PHONE)
    laptop = sign_in(client, "boss")
    assert end_mine(client, laptop, id_of(client, phone)).status_code == 204
    assert try_refresh(client, phone).status_code == 401
    assert try_refresh(client, laptop).status_code == 200


def test_an_old_device_cannot_end_the_sessions_made_after_a_password_change(client, db, boss):
    old = sign_in(client, "boss", PHONE)
    laptop = sign_in(client, "boss")
    client.put(
        "/auth/me/password",
        headers=bearer(laptop),
        json={"current_password": PASSWORD, "new_password": PASSWORD + " again"},
    )
    new = client.post(
        "/auth/login", json={"username": "boss", "password": PASSWORD + " again"}
    ).json()
    assert try_refresh(client, old).status_code == 401
    assert try_refresh(client, new).status_code == 200
    assert "sessions_revoked" not in db.scalars(select(LoginLog.event)).all()


def test_a_spent_token_of_a_live_session_still_ends_every_session(client, db, boss):
    stolen = sign_in(client, "boss", PHONE)
    laptop = sign_in(client, "boss")
    refresh(client, stolen)
    assert try_refresh(client, stolen).status_code == 401
    assert try_refresh(client, laptop).status_code == 401
    assert "sessions_revoked" in db.scalars(select(LoginLog.event)).all()


def test_only_your_own_live_sessions_can_be_ended_through_your_profile(client, conn, boss):
    make_login_user(conn, "op", "operator")
    other = sign_in(client, "op")
    tokens = sign_in(client, "boss")
    theirs = id_of(client, other)
    assert end_mine(client, tokens, theirs).status_code == 404
    assert end_mine(client, tokens, "nothing").status_code == 404
    assert try_refresh(client, other).status_code == 200


def test_an_admin_can_sign_out_another_persons_session(client, db, conn, boss):
    op = make_login_user(conn, "op", "operator")
    first = sign_in(client, "op", PHONE)
    second = sign_in(client, "op")
    admin = sign_in(client, "boss")
    target = id_of(client, first)
    assert end_theirs(client, admin, op, target).status_code == 204
    assert try_refresh(client, first).status_code == 401
    assert try_refresh(client, second).status_code == 200
    assert end_theirs(client, admin, op, target).status_code == 404  # already ended
    entry = db.scalars(select(ActivityLog)).one()
    assert (entry.user_id, entry.action, entry.resource, entry.resource_id) == (
        boss, "sign_out", "session", op,
    )
    assert "op" in entry.summary


def test_a_session_is_only_ended_under_the_user_it_belongs_to(client, conn, boss):
    op = make_login_user(conn, "op", "operator")
    admin = sign_in(client, "boss")
    assert end_theirs(client, admin, op, id_of(client, admin)).status_code == 404
    assert try_refresh(client, admin).status_code == 200


def test_ending_your_own_session_is_logged(client, db, boss):
    phone = sign_in(client, "boss", PHONE)
    laptop = sign_in(client, "boss")
    end_mine(client, laptop, id_of(client, phone))
    entry = db.scalars(select(ActivityLog)).one()
    assert (entry.user_id, entry.action, entry.resource) == (boss, "sign_out", "session")


@pytest.mark.parametrize("role", ["operator", "agent", "auditor"])
def test_reading_logs_is_not_enough_to_sign_people_out(client, conn, boss, role):
    make_login_user(conn, "caller", role)
    victim = sign_in(client, "boss")
    caller = sign_in(client, "caller")
    assert end_theirs(client, caller, boss, id_of(client, victim)).status_code == 403
    assert try_refresh(client, victim).status_code == 200


def test_the_log_marks_the_callers_own_session(client, conn, boss):
    make_login_user(conn, "op", "operator")
    sign_in(client, "op")
    admin = sign_in(client, "boss")
    assert {(s["username"], s["current"]) for s in everyone(client, admin)["items"]} == {
        ("op", False), ("boss", True),
    }


@pytest.mark.parametrize("by", ["owner", "admin"])
def test_signing_out_a_session_stops_its_notifications(client, db, conn, monkeypatch, by):
    public, _ = push.new_vapid_keys()
    monkeypatch.setattr(settings, "vapid_public_key", public)
    op = make_login_user(conn, "op", "operator")
    make_login_user(conn, "boss", "admin")
    phone = sign_in(client, "op", PHONE)
    laptop = sign_in(client, "op")
    for n, tokens in enumerate((phone, laptop)):
        body = {"endpoint": f"https://push.example.com/{n}", "keys": {"p256dh": "k", "auth": "a"}}
        # subscribed before a refresh: still the same session afterwards
        assert client.put("/auth/me/push", json=body, headers=bearer(tokens)).status_code == 204
    phone = refresh(client, phone, PHONE)
    target = id_of(client, phone)
    if by == "owner":
        assert end_mine(client, laptop, target).status_code == 204
    else:
        assert end_theirs(client, sign_in(client, "boss"), op, target).status_code == 204
    assert db.scalars(select(PushSubscription.endpoint)).all() == ["https://push.example.com/1"]
