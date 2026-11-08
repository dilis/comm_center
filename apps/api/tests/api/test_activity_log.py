"""Activity log: what people did is recorded with the change itself; reads and failures are not."""

import pytest
from sqlalchemy import select

from app.models import ActivityLog
from tests.api.conftest import PASSWORD, auth_header
from tests.db.helpers import (
    make_contact,
    make_inbound_agent,
    make_login_user,
    make_message,
    make_phone,
)

pytestmark = pytest.mark.db


def rows(db, **where):
    stmt = select(ActivityLog).order_by(ActivityLog.id)
    for column, value in where.items():
        stmt = stmt.where(getattr(ActivityLog, column) == value)
    return list(db.scalars(stmt))


@pytest.fixture
def boss(conn):
    return make_login_user(conn, "boss", "admin")


def test_creating_updating_and_deleting_a_contact_is_logged(client, db, boss):
    h = auth_header(client, "boss")
    cid = client.post("/contacts", headers=h, json={"name": "Ana"}).json()["id"]
    client.put(f"/contacts/{cid}", headers=h, json={"name": "Ana B"})
    client.delete(f"/contacts/{cid}", headers=h)
    got = [(r.action, r.resource, r.resource_id, r.user_id) for r in rows(db)]
    assert got == [("create", "contact", cid, boss), ("update", "contact", cid, boss),
                   ("delete", "contact", cid, boss)]
    assert "Ana" in rows(db)[0].summary
    assert rows(db)[0].ip == "testclient"


def test_user_management_is_logged_without_secrets(client, db, boss):
    h = auth_header(client, "boss")
    uid = client.post("/users", headers=h, json={
        "username": "newbie", "password": "a long enough pass", "contact": {"name": "New B"},
    }).json()["id"]
    client.put(f"/users/{uid}", headers=h, json={"is_active": False})
    client.post(f"/users/{uid}/unlock", headers=h)
    client.delete(f"/users/{uid}", headers=h)
    assert [(r.action, r.resource, r.resource_id) for r in rows(db)] == [
        ("create", "user", uid), ("update", "user", uid), ("unlock", "user", uid),
        ("delete", "user", uid),
    ]
    assert not any("a long enough pass" in r.summary for r in rows(db))


def test_messages_are_logged_without_their_text(client, conn, db, boss):
    h = auth_header(client, "boss")
    cid = make_contact(conn, "Rey")
    make_phone(conn, cid, "+639171234567")
    sent = client.post("/messages/send", headers=h, json={"contact_id": cid, "content": "secret words"})
    client.post("/messages/send-bulk", headers=h, json={"contact_ids": [cid], "content": "secret words"})
    incoming = make_message(conn, cid, owner_id=make_inbound_agent(conn))
    client.post(f"/messages/{incoming}/reply", headers=h, json={"content": "secret words"})
    client.delete(f"/messages/{sent.json()['id']}", headers=h)
    got = rows(db)
    assert [(r.action, r.resource) for r in got] == [
        ("send", "message"), ("send_bulk", "message"), ("reply", "message"), ("delete", "message"),
    ]
    assert got[0].resource_id == sent.json()["id"] and got[2].resource_id is not None
    assert "1" in got[1].summary  # how many were queued
    assert not any("secret words" in r.summary for r in got)


def test_own_account_changes_are_logged(client, db, boss):
    h = auth_header(client, "boss")
    client.patch("/auth/me/profile", headers=h, json={"name": "Boss Man"})
    client.put("/auth/me/phones", headers=h, json={"phones": [{"phone": "+639171230000"}]})
    client.put("/auth/me/password", headers=h,
               json={"current_password": PASSWORD, "new_password": "another long pass"})
    assert [(r.action, r.resource, r.resource_id) for r in rows(db)] == [
        ("update", "profile", boss), ("update", "phones", boss), ("change_password", "account", boss),
    ]
    assert not any("another long pass" in r.summary for r in rows(db))


def test_reads_failures_and_rejected_requests_are_not_logged(client, conn, db, boss):
    h = auth_header(client, "boss")
    client.get("/contacts", headers=h)
    client.get("/messages", headers=h)
    client.put("/contacts/999999", headers=h, json={"name": "x"})  # 404
    client.post("/contacts", headers=h, json={})  # 422
    client.put("/auth/me/password", headers=h, json={"current_password": "wrong password!", "new_password": "another long pass"})
    make_login_user(conn, "nobody")
    agent = auth_header(client, "nobody")
    client.post("/contacts", headers=agent, json={"name": "x"})  # 403
    assert rows(db) == []


def test_viewing_the_logs_is_not_itself_logged(client, db, boss):
    h = auth_header(client, "boss")
    client.get("/logs/activity", headers=h)
    client.get("/logs/logins", headers=h)
    assert rows(db) == []


def test_list_shows_newest_first_with_who_did_it(client, db, boss):
    h = auth_header(client, "boss")
    client.post("/contacts", headers=h, json={"name": "First"})
    client.post("/contacts", headers=h, json={"name": "Second"})
    r = client.get("/logs/activity", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2 and body["page"] == 1
    assert [i["summary"] for i in body["items"]] == [rows(db)[1].summary, rows(db)[0].summary]
    first = body["items"][0]
    assert first["username"] == "boss" and first["user_id"] == boss
    assert {"id", "name", "action", "resource", "resource_id", "ip", "created_at"} <= set(first)


def test_list_filters_and_pages(client, conn, db, boss):
    make_login_user(conn, "other", "operator")
    h, other = auth_header(client, "boss"), auth_header(client, "other")
    client.post("/contacts", headers=h, json={"name": "Alpha"})
    cid = client.post("/contacts", headers=other, json={"name": "Beta"}).json()["id"]
    client.delete(f"/contacts/{cid}", headers=h)

    def total(**params):
        return client.get("/logs/activity", headers=h, params=params).json()["total"]

    assert total() == 3
    assert total(action="create") == 2
    assert total(resource="contact") == 3 and total(resource="user") == 0
    assert total(user_id=boss) == 2
    assert total(q="Beta") == 2  # create and delete both mention it
    assert total(q="other") == 1  # a person's username matches too
    page = client.get("/logs/activity", headers=h, params={"page_size": 2, "page": 2}).json()
    assert page["total"] == 3 and len(page["items"]) == 1


def test_a_deleted_users_entries_still_show_their_name(client, conn, db, boss):
    gone = make_login_user(conn, "leaver", "operator")
    client.post("/contacts", headers=auth_header(client, "leaver"), json={"name": "Kept"})
    client.delete(f"/users/{gone}", headers=auth_header(client, "boss"))
    items = client.get("/logs/activity", headers=auth_header(client, "boss"),
                       params={"user_id": gone}).json()["items"]
    assert [i["username"] for i in items] == ["leaver"]


def test_only_log_readers_may_list(client, conn):
    make_login_user(conn, "viewer", "auditor")
    make_login_user(conn, "op", "operator")
    assert client.get("/logs/activity", headers=auth_header(client, "viewer")).status_code == 200
    assert client.get("/logs/activity", headers=auth_header(client, "op")).status_code == 403
    assert client.get("/logs/activity").status_code == 401
