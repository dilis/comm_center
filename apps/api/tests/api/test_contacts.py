import pytest

from tests.api.conftest import auth_header
from tests.db.helpers import (
    make_contact,
    make_inbound_agent,
    make_login_user,
    make_phone,
    make_user,
)

pytestmark = pytest.mark.db


@pytest.fixture
def boss(conn):
    return make_login_user(conn, "boss", "admin")


@pytest.fixture
def h(client, boss):
    return auth_header(client, "boss")


def create(client, h, **body):
    body.setdefault("first_name", body.pop("name", "Ana"))
    return client.post("/contacts", json=body, headers=h)


# ---- create / read -------------------------------------------------------------------------


def test_create_contact_with_phones_sets_owner(client, h, boss):
    r = create(
        client,
        h,
        email="ana@example.com",
        notes="vip",
        phones=[
            {"phone": "0917 123 4567", "label": "mobile", "is_primary": True},
            {"phone": "+639181234567"},
        ],
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["owner_id"] == boss and body["type"] == "person" and body["user_id"] is None
    assert body["phones"] == [
        {"phone": "+639171234567", "label": "mobile", "is_primary": True},
        {"phone": "+639181234567", "label": None, "is_primary": False},
    ]
    assert client.get(f"/contacts/{body['id']}", headers=h).json() == body


def test_create_validation(client, h):
    assert create(client, h, name="").status_code == 422
    assert create(client, h, email="nope").status_code == 422
    assert create(client, h, type="robot").status_code == 422
    assert create(client, h, phones=[{"phone": "123"}]).status_code == 422
    assert (
        create(client, h, phones=[{"phone": "+639171234567"}, {"phone": "09171234567"}]).status_code
        == 422
    )
    two_primary = [
        {"phone": "+639171234567", "is_primary": True},
        {"phone": "+639181234567", "is_primary": True},
    ]
    assert create(client, h, phones=two_primary).status_code == 422


def test_phone_already_used_is_409_and_nothing_is_created(client, h):
    assert create(client, h, phones=[{"phone": "+639171234567"}]).status_code == 201
    assert create(client, h, name="Dup", phones=[{"phone": "+639171234567"}]).status_code == 409
    assert client.get("/contacts?q=Dup", headers=h).json()["total"] == 0


def test_get_missing_or_deleted_is_404(client, h):
    assert client.get("/contacts/99999", headers=h).status_code == 404
    cid = create(client, h).json()["id"]
    assert client.delete(f"/contacts/{cid}", headers=h).status_code == 204
    assert client.get(f"/contacts/{cid}", headers=h).status_code == 404


# ---- update --------------------------------------------------------------------------------


def test_update_contact_replaces_fields_and_phones(client, h):
    cid = create(client, h, phones=[{"phone": "+639171234567", "is_primary": True}]).json()["id"]
    r = client.put(
        f"/contacts/{cid}",
        headers=h,
        json={
            "first_name": "Ana B",
            "type": "entity",
            "email": None,
            "notes": "x",
            "phones": [{"phone": "+639181234567", "is_primary": True}],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["name"], body["type"], body["notes"]) == ("Ana B", "entity", "x")
    assert body["phones"] == [{"phone": "+639181234567", "label": None, "is_primary": True}]
    # the removed number is free again
    assert create(client, h, name="Other", phones=[{"phone": "+639171234567"}]).status_code == 201


def test_update_without_phones_keeps_them(client, h):
    cid = create(client, h, phones=[{"phone": "+639171234567"}]).json()["id"]
    r = client.put(f"/contacts/{cid}", headers=h, json={"first_name": "New"})
    assert r.json()["name"] == "New" and len(r.json()["phones"]) == 1


def test_update_cannot_change_owner(client, h, boss, conn):
    cid = create(client, h).json()["id"]
    r = client.put(f"/contacts/{cid}", headers=h, json={"first_name": "A", "owner_id": 1})
    assert r.json()["owner_id"] == boss


def test_update_phone_conflict_keeps_old_phones(client, h):
    create(client, h, name="Other", phones=[{"phone": "+639181234567"}])
    cid = create(client, h, phones=[{"phone": "+639171234567"}]).json()["id"]
    r = client.put(
        f"/contacts/{cid}", headers=h, json={"first_name": "Ana", "phones": [{"phone": "+639181234567"}]}
    )
    assert r.status_code == 409
    assert client.get(f"/contacts/{cid}", headers=h).json()["phones"][0]["phone"] == "+639171234567"


# ---- delete --------------------------------------------------------------------------------


def test_delete_soft_deletes_contact_and_frees_phones(client, h, conn):
    cid = create(client, h, phones=[{"phone": "+639171234567"}]).json()["id"]
    assert client.delete(f"/contacts/{cid}", headers=h).status_code == 204
    assert client.delete(f"/contacts/{cid}", headers=h).status_code == 404
    assert create(client, h, name="Reuse", phones=[{"phone": "+639171234567"}]).status_code == 201


def test_cannot_delete_contact_linked_to_active_user(client, h, conn):
    uid = make_user(conn, "linked")
    cid = conn.exec_driver_sql("SELECT contact_id FROM users WHERE id=%s", (uid,)).scalar_one()
    r = client.delete(f"/contacts/{cid}", headers=h)
    assert r.status_code == 409


def test_can_delete_contact_after_its_user_is_soft_deleted(client, h, conn):
    from tests.db.helpers import soft_delete

    uid = make_user(conn, "gone")
    cid = conn.exec_driver_sql("SELECT contact_id FROM users WHERE id=%s", (uid,)).scalar_one()
    soft_delete(conn, "users", uid)
    assert client.delete(f"/contacts/{cid}", headers=h).status_code == 204


# ---- list: filter, sort, pagination --------------------------------------------------------


def test_list_envelope_pagination_and_default_sort(client, h):
    for n in ("Cara", "Abe", "Bea"):
        create(client, h, name=n)
    body = client.get("/contacts?page_size=2", headers=h).json()
    assert set(body) == {"items", "total", "page", "page_size"}
    assert body["total"] >= 3 and len(body["items"]) == 2 and body["page_size"] == 2
    names = [
        c["name"]
        for c in client.get("/contacts?page_size=100&sort=name", headers=h).json()["items"]
    ]
    assert names == sorted(names, key=str.lower)
    desc = [
        c["name"]
        for c in client.get("/contacts?page_size=100&sort=name&order=desc", headers=h).json()[
            "items"
        ]
    ]
    assert desc == names[::-1]


def test_list_search_name_email_phone_and_wildcards_are_literal(client, h):
    create(client, h, name="Zed Zulu", email="zed@example.com", phones=[{"phone": "+639171230000"}])
    create(client, h, name="Yan Yoyo")
    names = lambda q: {c["name"] for c in client.get(f"/contacts?q={q}", headers=h).json()["items"]}
    assert names("Zulu") == {"Zed Zulu"}
    assert names("zed@example") == {"Zed Zulu"}
    assert names("9171230000") == {"Zed Zulu"}
    assert names("%25") == set()  # a literal %, not a wildcard


def test_list_filter_by_type_and_bad_sort(client, h):
    create(client, h, name="Acme", type="entity")
    items = client.get("/contacts?type=entity&page_size=100", headers=h).json()["items"]
    assert items and all(c["type"] == "entity" for c in items)
    assert client.get("/contacts?sort=password", headers=h).status_code == 422


def test_list_includes_phones_and_linked_user(client, h, conn):
    uid = make_user(conn, "linked")
    cid = conn.exec_driver_sql("SELECT contact_id FROM users WHERE id=%s", (uid,)).scalar_one()
    make_phone(conn, cid, "+639175550000", is_primary=1)
    items = client.get("/contacts?q=linked", headers=h).json()["items"]
    assert items[0]["user_id"] == uid and items[0]["phones"][0]["phone"] == "+639175550000"


# ---- permission scope ----------------------------------------------------------------------


def test_read_all_roles_see_everyone_but_cannot_write(client, conn):
    cid = make_contact(conn, "Hidden Gem")
    for role in ("agent", "auditor"):
        make_login_user(conn, role, role)
        h = auth_header(client, role)
        assert client.get(f"/contacts/{cid}", headers=h).status_code == 200
        assert client.post("/contacts", json={"first_name": "x"}, headers=h).status_code == 403
        assert client.put(f"/contacts/{cid}", json={"first_name": "x"}, headers=h).status_code == 403
        assert client.delete(f"/contacts/{cid}", headers=h).status_code == 403


def test_operator_can_create_and_update_but_not_delete(client, conn):
    make_login_user(conn, "op", "operator")
    h = auth_header(client, "op")
    cid = create(client, h).json()["id"]
    assert client.put(f"/contacts/{cid}", json={"first_name": "Renamed"}, headers=h).status_code == 200
    assert client.delete(f"/contacts/{cid}", headers=h).status_code == 403


def test_user_without_any_contacts_permission_is_forbidden(client, conn):
    make_login_user(conn, "msgonly", "messages_agent")
    h = auth_header(client, "msgonly")
    assert client.get("/contacts", headers=h).status_code == 403
    assert client.get("/contacts/1", headers=h).status_code == 403


def test_read_own_user_sees_and_edits_only_own_contacts(client, conn):
    from tests.db.helpers import make_group_with

    me = make_login_user(conn, "mine")
    make_group_with(
        conn,
        me,
        "own_contacts",
        ("contacts", "create"),
        ("contacts", "read_own"),
        ("contacts", "update"),
        ("contacts", "delete"),
    )
    h = auth_header(client, "mine")
    mine = create(client, h, name="Mine").json()["id"]
    theirs = make_contact(conn, "Theirs")  # owned by system
    body = client.get("/contacts?page_size=100", headers=h).json()
    assert [c["id"] for c in body["items"]] == [mine] and body["total"] == 1
    for call in (
        lambda: client.get(f"/contacts/{theirs}", headers=h),
        lambda: client.put(f"/contacts/{theirs}", json={"first_name": "x"}, headers=h),
        lambda: client.delete(f"/contacts/{theirs}", headers=h),
    ):
        assert call().status_code == 404
    assert client.delete(f"/contacts/{mine}", headers=h).status_code == 204


def test_auto_created_contacts_are_visible_to_read_all_only(client, conn):
    agent = make_inbound_agent(conn)
    cid = make_contact(conn, "+639170000001", owner_id=agent)
    make_login_user(conn, "viewer", "contacts_viewer")
    assert client.get(f"/contacts/{cid}", headers=auth_header(client, "viewer")).status_code == 200


def test_unauthenticated(client):
    for call in (
        client.get("/contacts"),
        client.post("/contacts", json={"first_name": "x"}),
        client.get("/contacts/1"),
        client.put("/contacts/1", json={"first_name": "x"}),
        client.delete("/contacts/1"),
    ):
        assert call.status_code == 401


# ---- name parts ----------------------------------------------------------------------------

def test_name_is_first_middle_and_last_joined(client, h):
    r = create(client, h, first_name="Ana", middle_name="Maria", last_name="Cruz")
    body = r.json()
    assert r.status_code == 201
    assert (body["first_name"], body["middle_name"], body["last_name"]) == ("Ana", "Maria", "Cruz")
    assert body["name"] == "Ana Maria Cruz"


def test_middle_and_last_names_are_optional_and_blank_means_none(client, h):
    body = create(client, h, first_name=" Ana ", middle_name="  ", last_name="").json()
    assert (body["first_name"], body["middle_name"], body["last_name"]) == ("Ana", None, None)
    assert body["name"] == "Ana"


def test_a_first_name_is_required(client, h):
    assert client.post("/contacts", json={"last_name": "Cruz"}, headers=h).status_code == 422
    assert create(client, h, first_name="  ").status_code == 422


def test_an_entity_has_only_a_first_name(client, h):
    assert create(client, h, type="entity", first_name="Acme", last_name="Inc").status_code == 422
    assert create(client, h, type="entity", first_name="Acme Inc").json()["name"] == "Acme Inc"


def test_search_and_sort_use_the_full_name(client, h):
    create(client, h, first_name="Zed", middle_name="Q", last_name="Zulu")
    create(client, h, first_name="Yan", last_name="Yoyo")
    names = [c["name"] for c in client.get("/contacts?q=Q Zulu", headers=h).json()["items"]]
    assert names == ["Zed Q Zulu"]
    names = [c["name"] for c in client.get("/contacts?sort=name", headers=h).json()["items"]]
    assert names.index("Yan Yoyo") < names.index("Zed Q Zulu")
