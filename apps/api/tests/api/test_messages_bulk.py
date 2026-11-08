import pytest
from sqlalchemy import text

from tests.api.conftest import auth_header
from tests.db.helpers import make_contact, make_group_with, make_login_user, make_phone, soft_delete

pytestmark = pytest.mark.db


@pytest.fixture
def boss(conn):
    return make_login_user(conn, "boss", "admin")


@pytest.fixture
def h(client, boss):
    return auth_header(client, "boss")


def person(conn, name, *numbers, owner_id=1):
    contact_id = make_contact(conn, name, owner_id=owner_id)
    for i, number in enumerate(numbers):
        make_phone(conn, contact_id, number, is_primary=1 if i == 0 else 0)
    return contact_id


def bulk(client, h, contact_ids, content="hello all"):
    return client.post(
        "/messages/send-bulk", json={"contact_ids": contact_ids, "content": content}, headers=h
    )


def test_one_message_is_queued_per_contact_to_each_primary_number(client, h, boss, conn):
    ana = person(conn, "Ana", "+639171111111", "+639172222222")
    ben = person(conn, "Ben", "+639173333333")
    r = bulk(client, h, [ana, ben])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["skipped"] == []
    assert [(m["contact_id"], m["phone_number"]) for m in body["queued"]] == [
        (ana, "+639171111111"),
        (ben, "+639173333333"),
    ]
    for m in body["queued"]:
        assert (m["status"], m["direction"], m["owner_id"], m["content"]) == (
            "queued",
            "outbound",
            boss,
            "hello all",
        )
        assert m["contact_name"] in ("Ana", "Ben")
    assert conn.execute(text("SELECT COUNT(*) FROM messages")).scalar_one() == 2


def test_a_contact_without_a_primary_uses_its_first_number(client, h, conn):
    cid = make_contact(conn, "NoPrimary")
    make_phone(conn, cid, "+639171110000")
    make_phone(conn, cid, "+639172220000")
    assert bulk(client, h, [cid]).json()["queued"][0]["phone_number"] == "+639171110000"


def test_contacts_that_cannot_be_messaged_are_skipped_and_the_rest_still_go(client, h, conn):
    ana = person(conn, "Ana", "+639171111111")
    nophone = make_contact(conn, "No Phone")
    gone = person(conn, "Gone", "+639174444444")
    soft_delete(conn, "contacts", gone)
    r = bulk(client, h, [nophone, ana, gone, 99999])
    assert r.status_code == 201
    body = r.json()
    assert [m["contact_id"] for m in body["queued"]] == [ana]
    assert body["skipped"] == [
        {"contact_id": nophone, "reason": "no phone number"},
        {"contact_id": gone, "reason": "contact not found"},
        {"contact_id": 99999, "reason": "contact not found"},
    ]


def test_everyone_skipped_queues_nothing(client, h, conn):
    nophone = make_contact(conn, "No Phone")
    r = bulk(client, h, [nophone])
    assert r.status_code == 201 and r.json()["queued"] == [] and len(r.json()["skipped"]) == 1
    assert conn.execute(text("SELECT COUNT(*) FROM messages")).scalar_one() == 0


def test_repeated_ids_get_one_message(client, h, conn):
    ana = person(conn, "Ana", "+639171111111")
    r = bulk(client, h, [ana, ana, ana])
    assert [m["contact_id"] for m in r.json()["queued"]] == [ana] and r.json()["skipped"] == []


def test_the_order_of_the_request_is_kept(client, h, conn):
    ids = [person(conn, f"P{i}", f"+63917{i:07d}") for i in range(1, 6)]
    shuffled = [ids[3], ids[0], ids[4], ids[1], ids[2]]
    assert [m["contact_id"] for m in bulk(client, h, shuffled).json()["queued"]] == shuffled


def test_contacts_the_caller_cannot_read_are_reported_as_not_found(client, conn):
    me = make_login_user(conn, "narrow")
    make_group_with(conn, me, "narrow_send", ("messages", "create"), ("contacts", "read_own"))
    mine = person(conn, "Mine", "+639171111111", owner_id=me)
    theirs = person(conn, "Theirs", "+639172222222")  # owned by someone else
    r = bulk(client, auth_header(client, "narrow"), [mine, theirs])
    assert [m["contact_id"] for m in r.json()["queued"]] == [mine]
    assert r.json()["skipped"] == [{"contact_id": theirs, "reason": "contact not found"}]


def test_a_caller_with_no_contacts_access_is_forbidden(client, conn):
    me = make_login_user(conn, "sendonly")
    make_group_with(conn, me, "send_only", ("messages", "create"))
    assert bulk(client, auth_header(client, "sendonly"), [1]).status_code == 403


def test_validation(client, h, conn):
    ana = person(conn, "Ana", "+639171111111")
    assert bulk(client, h, []).status_code == 422
    assert bulk(client, h, [ana], content="").status_code == 422
    assert bulk(client, h, [ana], content="   ").status_code == 422
    assert bulk(client, h, [ana], content="x" * 1601).status_code == 422
    assert bulk(client, h, [ana], content="x" * 1600).status_code == 201
    assert bulk(client, h, list(range(1, 502))).status_code == 422  # at most 500
    assert client.post("/messages/send-bulk", json={"content": "x"}, headers=h).status_code == 422
    assert bulk(client, h, ["a"]).status_code == 422


def test_client_supplied_owner_and_status_are_ignored(client, h, boss, conn):
    ana = person(conn, "Ana", "+639171111111")
    r = client.post(
        "/messages/send-bulk",
        headers=h,
        json={
            "contact_ids": [ana],
            "content": "x",
            "owner_id": 1,
            "status": "sent",
        },
    )
    assert r.json()["queued"][0]["owner_id"] == boss and r.json()["queued"][0]["status"] == "queued"


@pytest.mark.parametrize(
    "role, allowed", [("admin", True), ("operator", True), ("agent", True), ("auditor", False)]
)
def test_who_may_send_to_many(client, conn, role, allowed):
    make_login_user(conn, "caller", role)
    ana = person(conn, "Ana", "+639171111111")
    assert (bulk(client, auth_header(client, "caller"), [ana]).status_code == 201) is allowed


def test_the_messages_are_visible_to_their_sender_afterwards(client, conn):
    make_login_user(conn, "ag", "agent")
    h = auth_header(client, "ag")
    ids = [person(conn, f"P{i}", f"+63917{i:07d}") for i in range(1, 4)]
    bulk(client, h, ids)
    assert client.get("/messages", headers=h).json()["total"] == 3
    assert client.get("/messages/counts", headers=h).json() == {"all": 3, "sent": 3, "received": 0, "unread": 0}


def test_unauthenticated(client):
    assert (
        client.post("/messages/send-bulk", json={"contact_ids": [1], "content": "x"}).status_code
        == 401
    )


def test_each_recipient_gets_their_own_name(client, h, conn):
    ana = person(conn, "Ana Cruz", "+639171111111")
    ben = person(conn, "Ben Lim", "+639172222222")
    body = bulk(client, h, [ana, ben], content="Dear {{name}}, see you Sunday").json()
    assert [m["content"] for m in body["queued"]] == [
        "Dear Ana Cruz, see you Sunday",
        "Dear Ben Lim, see you Sunday",
    ]


def test_unknown_placeholders_reject_the_whole_request(client, h, conn):
    ana = person(conn, "Ana", "+639171111111")
    r = bulk(client, h, [ana], content="Hi {{first_name}}")
    assert r.status_code == 422 and "unknown placeholder {{first_name}}" in r.text
    assert conn.execute(text("SELECT COUNT(*) FROM messages")).scalar_one() == 0


def test_a_recipient_whose_name_makes_the_text_too_long_is_skipped_not_the_others(client, h, conn):
    short = person(conn, "Al", "+639171111111")
    long_name = person(conn, "N" * 50, "+639172222222")
    body = bulk(
        client, h, [short, long_name], content="{{name}}" * 150
    ).json()  # 300 vs 7500 characters
    assert [m["contact_id"] for m in body["queued"]] == [short]
    assert body["skipped"] == [
        {"contact_id": long_name, "reason": "message too long once the name is inserted"}
    ]
