"""Sessions: one per sign-in, carried across refresh token rotation. Listed for yourself on
``/auth/me/sessions`` and for everyone on ``/logs/sessions``."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.clock import utcnow
from app.models import RefreshToken, User
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
