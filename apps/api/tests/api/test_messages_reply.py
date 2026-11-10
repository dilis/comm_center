import pytest
from sqlalchemy import text

from tests.api.conftest import auth_header
from tests.db.helpers import (
    make_contact,
    make_group_with,
    make_inbound_agent,
    make_login_user,
    make_message,
    make_phone,
    soft_delete,
)

pytestmark = pytest.mark.db


@pytest.fixture
def boss(conn):
    return make_login_user(conn, "boss", "admin")


@pytest.fixture
def h(client, boss):
    return auth_header(client, "boss")


@pytest.fixture
def agent(conn):
    return make_inbound_agent(conn)


@pytest.fixture
def ana(conn):
    cid = make_contact(conn, first_name="Ana", last_name="Cruz")
    make_phone(conn, cid, "+639171234567", is_primary=1)
    return cid


@pytest.fixture
def received(conn, agent, ana):
    return make_message(conn, ana, owner_id=agent, status="received", content="Are you coming?")


def reply(client, h, message_id, content="Yes, see you there"):
    return client.post(f"/messages/{message_id}/reply", json={"content": content}, headers=h)


def test_reply_queues_a_message_to_the_sender_linked_to_the_original(
    client, h, boss, ana, received
):
    r = reply(client, h, received)
    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["status"], body["direction"], body["owner_id"]) == ("queued", "outbound", boss)
    assert (body["contact_id"], body["contact_name"], body["phone_number"]) == (
        ana,
        "Ana Cruz",
        "+639171234567",
    )
    assert body["content"] == "Yes, see you there" and body["reply_to_id"] == received
    assert client.get(f"/messages/{body['id']}", headers=h).json()["reply_to_id"] == received


def test_ordinary_messages_have_no_reply_link(client, h, received, ana):
    sent = client.post(
        "/messages/send", json={"contact_id": ana, "content": "hi"}, headers=h
    ).json()
    assert sent["reply_to_id"] is None
    assert client.get(f"/messages/{received}", headers=h).json()["reply_to_id"] is None


def test_the_reply_goes_to_the_number_the_message_came_from(client, h, conn, agent, ana):
    other_number = make_message(
        conn, ana, owner_id=agent, status="received", phone_number="+639179999999"
    )
    assert (
        reply(client, h, other_number).json()["phone_number"] == "+639179999999"
    )  # not the contact's current one


def test_the_reply_can_use_the_senders_name(client, h, received):
    assert reply(client, h, received, "Hi {{name}}!").json()["content"] == "Hi Ana Cruz!"


def test_replying_still_works_after_the_contact_was_deleted(client, h, conn, ana, received):
    soft_delete(conn, "contacts", ana)
    r = reply(client, h, received, "Hi {{name}}")
    assert r.status_code == 201 and r.json()["content"] == "Hi Ana Cruz"


def test_a_message_can_be_replied_to_more_than_once(client, h, received):
    assert reply(client, h, received, "one").status_code == 201
    assert reply(client, h, received, "two").status_code == 201
    assert conn_count(client, h) == 3


def conn_count(client, h):
    return client.get("/messages", headers=h).json()["total"]


def test_only_received_messages_can_be_replied_to(client, h, ana):
    mine = client.post(
        "/messages/send", json={"contact_id": ana, "content": "hi"}, headers=h
    ).json()["id"]
    r = reply(client, h, mine)
    assert r.status_code == 422 and "only received messages" in r.text


def test_unknown_or_deleted_messages_are_404(client, h, conn, received):
    assert reply(client, h, 99999).status_code == 404
    soft_delete(conn, "messages", received)
    assert reply(client, h, received).status_code == 404


def test_validation(client, h, conn, received):
    assert reply(client, h, received, "").status_code == 422
    assert reply(client, h, received, "   ").status_code == 422
    assert reply(client, h, received, "x" * 1601).status_code == 422
    r = reply(client, h, received, "Hi {{nom}}")
    assert r.status_code == 422 and "unknown placeholder" in r.text
    assert client.post(f"/messages/{received}/reply", json={}, headers=h).status_code == 422


def test_the_name_may_not_push_the_reply_over_the_limit(client, h, conn, agent):
    long = make_contact(conn, "N" * 50)
    make_phone(conn, long, "+639175550000")
    msg = make_message(conn, long, owner_id=agent, status="received", phone_number="+639175550000")
    r = reply(client, h, msg, "{{name}}" * 150)
    assert r.status_code == 422 and "too long once the name is inserted" in r.text


def test_an_agent_can_reply_to_received_messages(client, conn, received):
    make_login_user(conn, "ag", "agent")
    assert reply(client, auth_header(client, "ag"), received).status_code == 201


def test_replying_needs_no_contacts_access_only_that_you_can_see_the_message(
    client, conn, received
):
    me = make_login_user(conn, "inbox")
    make_group_with(conn, me, "inbox_only", ("messages", "create"), ("messages", "read_received"))
    assert reply(client, auth_header(client, "inbox"), received).status_code == 201


def test_a_message_you_cannot_see_is_404_not_forbidden(client, conn, received):
    me = make_login_user(conn, "ownonly")
    make_group_with(conn, me, "own_only", ("messages", "create"), ("messages", "read_own"))
    assert reply(client, auth_header(client, "ownonly"), received).status_code == 404


def test_roles_without_messages_create_are_forbidden(client, conn, received):
    make_login_user(conn, "aud", "auditor")
    assert reply(client, auth_header(client, "aud"), received).status_code == 403


def test_unauthenticated(client, received):
    assert client.post(f"/messages/{received}/reply", json={"content": "x"}).status_code == 401


def test_the_new_message_is_a_normal_queued_one_for_the_worker(client, h, conn, received):
    new_id = reply(client, h, received).json()["id"]
    row = conn.execute(
        text("SELECT status, owner_id, gsm_device_id, reply_to_id FROM messages WHERE id=:i"),
        {"i": new_id},
    ).one()
    assert row.status == "queued" and row.gsm_device_id is None and row.reply_to_id == received


def test_the_reply_can_use_first_and_last_names(client, h, received):
    out = reply(client, h, received, "Dear {{first_name}} {{last_name}}, hello {{name}}")
    assert out.json()["content"] == "Dear Ana Cruz, hello Ana Cruz"
