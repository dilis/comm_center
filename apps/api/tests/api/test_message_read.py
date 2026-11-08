"""Unread state is per user: reading a received message marks it read for the reader only."""

import pytest
from sqlalchemy import text

from tests.api.conftest import auth_header
from tests.db.helpers import (
    make_contact,
    make_inbound_agent,
    make_login_user,
    make_message,
    make_phone,
)

pytestmark = pytest.mark.db


@pytest.fixture
def world(conn):
    ana = make_contact(conn, "Ana")
    make_phone(conn, ana, "+639171234567")
    agent = make_inbound_agent(conn)
    return {
        "admin": make_login_user(conn, "admin1", "admin"),
        "operator": make_login_user(conn, "op1", "operator"),
        "incoming": make_message(conn, ana, owner_id=agent, content="hi", status="received"),
        "ana": ana,
    }


def get(client, who, message_id):
    return client.get(f"/messages/{message_id}", headers=auth_header(client, who)).json()


def test_received_messages_start_unread_for_everyone(client, world):
    assert get(client, "admin1", world["incoming"])["unread"] is True
    assert get(client, "op1", world["incoming"])["unread"] is True


def test_marking_read_affects_only_the_reader(client, world):
    r = client.post(f"/messages/{world['incoming']}/read", headers=auth_header(client, "admin1"))
    assert r.status_code == 204
    assert get(client, "admin1", world["incoming"])["unread"] is False
    assert get(client, "op1", world["incoming"])["unread"] is True


def test_marking_read_twice_is_fine(client, world):
    h = auth_header(client, "admin1")
    for _ in range(2):
        assert client.post(f"/messages/{world['incoming']}/read", headers=h).status_code == 204


def test_the_list_carries_each_viewers_own_state(client, world):
    client.post(f"/messages/{world['incoming']}/read", headers=auth_header(client, "admin1"))

    def unread(who):
        items = client.get("/messages", headers=auth_header(client, who)).json()["items"]
        return {m["id"]: m["unread"] for m in items}

    assert unread("admin1") == {world["incoming"]: False}
    assert unread("op1") == {world["incoming"]: True}


def test_sent_messages_are_never_unread(client, world, conn):
    sent = make_message(conn, world["ana"], owner_id=world["admin"], content="out")
    assert get(client, "admin1", sent)["unread"] is False
    assert get(client, "op1", sent)["unread"] is False  # an operator reads all messages


def test_marking_a_sent_message_read_is_harmless(client, world, conn):
    sent = make_message(conn, world["ana"], owner_id=world["admin"], content="out")
    assert client.post(f"/messages/{sent}/read", headers=auth_header(client, "admin1")).status_code == 204
    assert conn.execute(text("SELECT COUNT(*) FROM message_read")).scalar_one() == 0


def test_you_cannot_mark_a_message_you_cannot_see(client, world, conn):
    other = make_login_user(conn, "agent1", "agent")
    mine_only = make_message(conn, world["ana"], owner_id=world["admin"], content="private")
    r = client.post(f"/messages/{mine_only}/read", headers=auth_header(client, "agent1"))
    assert r.status_code == 404 and other


def test_unknown_message_is_404(client, world):
    assert client.post("/messages/999999/read", headers=auth_header(client, "admin1")).status_code == 404


def test_replying_marks_the_original_read_for_the_replier(client, world):
    h = auth_header(client, "admin1")
    r = client.post(f"/messages/{world['incoming']}/reply", json={"content": "yes"}, headers=h)
    assert r.status_code == 201
    assert get(client, "admin1", world["incoming"])["unread"] is False
    assert get(client, "op1", world["incoming"])["unread"] is True
