import pytest
from sqlalchemy import text

from tests.api.conftest import auth_header
from tests.db.helpers import (
    insert,
    make_contact,
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
def ana(conn):
    cid = make_contact(conn, "Ana Cruz")
    make_phone(conn, cid, "+639171234567", label="home")
    make_phone(conn, cid, "+639181234567", label="work", is_primary=1)
    return cid


def send(client, h, **body):
    return client.post("/messages/send", json=body, headers=h)


# ---- send ----------------------------------------------------------------------------------


def test_send_queues_a_message_to_the_primary_phone(client, h, boss, ana):
    r = send(client, h, contact_id=ana, content="hello")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "queued" and body["direction"] == "outbound"
    assert body["owner_id"] == boss and body["contact_id"] == ana and body["channel"] == "gsm"
    assert body["phone_number"] == "+639181234567"  # the primary
    assert body["contact_name"] == "Ana Cruz" and body["content"] == "hello"
    assert body["sent_at"] is None and body["received_at"] is None and body["gsm_device_id"] is None


def test_send_without_primary_uses_the_first_phone(client, h, conn):
    cid = make_contact(conn, "NoPrimary")
    make_phone(conn, cid, "+639171110000")
    make_phone(conn, cid, "+639172220000")
    assert send(client, h, contact_id=cid, content="x").json()["phone_number"] == "+639171110000"


def test_send_to_a_chosen_number_of_the_contact(client, h, ana):
    r = send(client, h, contact_id=ana, content="x", phone="0917 123 4567")
    assert r.status_code == 201 and r.json()["phone_number"] == "+639171234567"


def test_send_rejects_a_number_not_on_the_contact(client, h, ana, conn):
    r = send(client, h, contact_id=ana, content="x", phone="+639175550000")
    assert r.status_code == 422
    conn.execute(
        text("UPDATE contact_phone SET deleted_at = NOW() WHERE phone_e164='+639171234567'")
    )
    assert send(client, h, contact_id=ana, content="x", phone="+639171234567").status_code == 422


def test_send_validation(client, h, ana, conn):
    assert send(client, h, contact_id=ana, content="").status_code == 422
    assert send(client, h, contact_id=ana, content="   ").status_code == 422
    assert send(client, h, contact_id=ana, content="x" * 1601).status_code == 422
    assert send(client, h, contact_id=ana, content="x" * 1600).status_code == 201
    assert send(client, h, contact_id=ana, content="x", phone="nope").status_code == 422
    assert send(client, h, content="x").status_code == 422
    assert send(client, h, contact_id=99999, content="x").status_code == 404
    nophone = make_contact(conn, "NoPhone")
    assert send(client, h, contact_id=nophone, content="x").status_code == 422


def test_send_to_deleted_contact_is_404(client, h, ana, conn):
    soft_delete(conn, "contacts", ana)
    assert send(client, h, contact_id=ana, content="x").status_code == 404


def test_send_ignores_client_supplied_owner_and_status(client, h, boss, ana):
    r = send(client, h, contact_id=ana, content="x", owner_id=1, status="sent", direction="inbound")
    assert r.json()["owner_id"] == boss and r.json()["status"] == "queued"
    assert r.json()["direction"] == "outbound"


def test_send_needs_messages_create_and_a_readable_contact(client, conn, ana):
    make_login_user(conn, "aud", "auditor")
    assert send(client, auth_header(client, "aud"), contact_id=ana, content="x").status_code == 403
    me = make_login_user(conn, "nocontacts")
    from tests.db.helpers import make_group_with

    make_group_with(conn, me, "send_only", ("messages", "create"))
    r = send(client, auth_header(client, "nocontacts"), contact_id=ana, content="x")
    assert r.status_code == 403


def test_agent_can_send_to_any_contact(client, conn, ana):
    make_login_user(conn, "ag", "agent")
    assert send(client, auth_header(client, "ag"), contact_id=ana, content="hi").status_code == 201


# ---- list, direction, tabs, counts -----------------------------------------------------------


@pytest.fixture
def mailbox(conn, boss, ana):
    """boss sent 2, another human sent 1, the device agent received 2, notification sent 1."""
    agent = make_inbound_agent(conn)
    other = make_login_user(conn, "other", "operator")
    notifier = conn.execute(text("SELECT id FROM users WHERE username='notification'")).scalar_one()
    ids = {
        "mine1": make_message(conn, ana, owner_id=boss, content="mine one"),
        "mine2": make_message(conn, ana, owner_id=boss, content="mine two", status="sent"),
        "theirs": make_message(conn, ana, owner_id=other, content="theirs"),
        "in1": make_message(conn, ana, owner_id=agent, content="in one", status="received"),
        "in2": make_message(conn, ana, owner_id=agent, content="in two", status="received"),
        "note": make_message(conn, ana, owner_id=notifier, content="auto"),
    }
    ids["agent"], ids["other"] = agent, other
    return ids


def listed(client, h, query=""):
    body = client.get(f"/messages?page_size=100&{query}", headers=h).json()
    return body, {m["id"] for m in body["items"]}


def test_admin_sees_all_with_computed_direction(client, h, mailbox):
    body, _ = listed(client, h)
    assert set(body) == {"items", "total", "page", "page_size"} and body["total"] == 6
    by_id = {m["id"]: m for m in body["items"]}
    assert by_id[mailbox["in1"]]["direction"] == "inbound"
    assert by_id[mailbox["note"]]["direction"] == "outbound"
    assert by_id[mailbox["mine1"]]["direction"] == "outbound"
    assert by_id[mailbox["in1"]]["contact_name"] == "Ana Cruz"


def test_direction_tabs(client, h, mailbox):
    _, sent = listed(client, h, "direction=sent")
    _, received = listed(client, h, "direction=received")
    _, every = listed(client, h, "direction=all")
    assert received == {mailbox["in1"], mailbox["in2"]}
    assert sent == {mailbox[k] for k in ("mine1", "mine2", "theirs", "note")}
    assert every == sent | received
    assert client.get("/messages?direction=sideways", headers=h).status_code == 422


def test_counts_per_tab_follow_the_scope(client, h, mailbox, conn):
    assert client.get("/messages/counts", headers=h).json() == {"all": 6, "sent": 4, "received": 2}
    make_login_user(conn, "ag", "agent")
    mine = make_message(
        conn,
        1,
        owner_id=conn.execute(text("SELECT id FROM users WHERE username='ag'")).scalar_one(),
    )
    assert mine
    counts = client.get("/messages/counts", headers=auth_header(client, "ag")).json()
    assert counts == {"all": 3, "sent": 1, "received": 2}


def test_filters_search_sort_and_pagination(client, h, mailbox, ana):
    _, ids = listed(client, h, "status=sent")
    assert ids == {mailbox["mine2"]}
    _, ids = listed(client, h, f"contact_id={ana}")
    assert len(ids) == 6
    _, ids = listed(client, h, "q=in%20o")
    assert ids == {mailbox["in1"]}
    _, ids = listed(client, h, "q=%25")  # a literal %, not a wildcard
    assert ids == set()
    newest_first = [m["id"] for m in listed(client, h)[0]["items"]]
    assert newest_first == sorted(newest_first, reverse=True)
    oldest_first = [m["id"] for m in listed(client, h, "order=asc")[0]["items"]]
    assert oldest_first == newest_first[::-1]
    page = client.get("/messages?page=2&page_size=4", headers=h).json()
    assert len(page["items"]) == 2 and page["total"] == 6
    assert client.get("/messages?status=bogus", headers=h).status_code == 422


def test_deleted_messages_are_hidden_from_list_and_counts(client, h, mailbox, conn):
    soft_delete(conn, "messages", mailbox["mine1"])
    body, ids = listed(client, h)
    assert mailbox["mine1"] not in ids and body["total"] == 5
    assert client.get("/messages/counts", headers=h).json()["all"] == 5


def test_messages_of_a_deleted_user_are_still_listed(client, h, mailbox, conn):
    soft_delete(conn, "users", mailbox["other"])
    body, ids = listed(client, h, "direction=sent")
    assert mailbox["theirs"] in ids
    assert {m["id"]: m["direction"] for m in body["items"]}[mailbox["theirs"]] == "outbound"


def test_inbound_message_reports_its_devices_id(client, h, mailbox, conn):
    dev = insert(
        conn,
        "gsm_device",
        name="d1",
        serial_port="/dev/x",
        phone_number="+639170000000",
        agent_user_id=mailbox["agent"],
        owner_id=1,
    )
    out = client.get(f"/messages/{mailbox['in1']}", headers=h).json()
    assert out["gsm_device_id"] == dev


def test_messages_are_never_exposed_for_update(client, h, mailbox):
    assert (
        client.put(f"/messages/{mailbox['mine1']}", json={"content": "x"}, headers=h).status_code
        == 405
    )
    assert (
        client.patch(f"/messages/{mailbox['mine1']}", json={"content": "x"}, headers=h).status_code
        == 405
    )


# ---- visibility by permission ----------------------------------------------------------------


def test_agent_sees_own_sent_plus_all_received_only(client, conn, mailbox, boss):
    me = make_login_user(conn, "ag", "agent")
    cid = make_contact(conn, "Zed")
    make_phone(conn, cid, "+639175551111")
    h = auth_header(client, "ag")
    mine = send(client, h, contact_id=cid, content="from agent").json()["id"]
    body, ids = listed(client, h)
    assert ids == {mine, mailbox["in1"], mailbox["in2"]} and body["total"] == 3
    for hidden in ("mine1", "theirs", "note"):  # another human's and the notification agent's
        assert client.get(f"/messages/{mailbox[hidden]}", headers=h).status_code == 404
    assert client.get(f"/messages/{mailbox['in1']}", headers=h).status_code == 200
    assert me


def test_read_own_only_user_does_not_see_received(client, conn, mailbox):
    from tests.db.helpers import make_group_with

    me = make_login_user(conn, "ownonly")
    make_group_with(conn, me, "own_msgs", ("messages", "read_own"))
    _, ids = listed(client, auth_header(client, "ownonly"))
    assert ids == set()
    _, received = listed(client, auth_header(client, "ownonly"), "direction=received")
    assert received == set()


def test_read_received_only_user_sees_inbound_only(client, conn, mailbox):
    from tests.db.helpers import make_group_with

    me = make_login_user(conn, "recvonly")
    make_group_with(conn, me, "recv_msgs", ("messages", "read_received"))
    _, ids = listed(client, auth_header(client, "recvonly"))
    assert ids == {mailbox["in1"], mailbox["in2"]}


@pytest.mark.parametrize("role", ["operator", "auditor"])
def test_read_all_roles_see_everything(client, conn, mailbox, role):
    make_login_user(conn, "r", role)
    body, _ = listed(client, auth_header(client, "r"))
    assert body["total"] == 6


def test_user_without_message_permissions_is_forbidden(client, conn, mailbox):
    make_login_user(conn, "nomsg", "contacts_viewer")
    h = auth_header(client, "nomsg")
    assert client.get("/messages", headers=h).status_code == 403
    assert client.get("/messages/counts", headers=h).status_code == 403
    assert client.get(f"/messages/{mailbox['in1']}", headers=h).status_code == 403


# ---- detail and delete -------------------------------------------------------------------------


def test_get_missing_message_is_404(client, h):
    assert client.get("/messages/99999", headers=h).status_code == 404


def test_delete_soft_deletes(client, h, mailbox):
    mid = mailbox["mine1"]
    assert client.delete(f"/messages/{mid}", headers=h).status_code == 204
    assert client.get(f"/messages/{mid}", headers=h).status_code == 404
    assert client.delete(f"/messages/{mid}", headers=h).status_code == 404


def test_delete_is_limited_to_roles_with_the_permission_and_to_visible_rows(client, conn, mailbox):
    make_login_user(conn, "op", "operator")
    assert (
        client.delete(
            f"/messages/{mailbox['mine1']}", headers=auth_header(client, "op")
        ).status_code
        == 403
    )
    me = make_login_user(conn, "ownerdel")
    from tests.db.helpers import make_group_with

    make_group_with(conn, me, "own_del", ("messages", "read_own"), ("messages", "delete"))
    h = auth_header(client, "ownerdel")
    assert (
        client.delete(f"/messages/{mailbox['mine1']}", headers=h).status_code == 404
    )  # not theirs


def test_unauthenticated(client):
    for call in (
        client.get("/messages"),
        client.get("/messages/counts"),
        client.get("/messages/1"),
        client.post("/messages/send", json={"contact_id": 1, "content": "x"}),
        client.delete("/messages/1"),
    ):
        assert call.status_code == 401
