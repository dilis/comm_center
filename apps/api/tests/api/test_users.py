import pytest
from sqlalchemy import text

from tests.api.conftest import auth_header
from tests.db.helpers import (
    make_contact,
    make_group_with,
    make_inbound_agent,
    make_login_user,
    make_phone,
)

pytestmark = pytest.mark.db

NEW = {"username": "newbie", "password": "a long enough pass", "contact": {"first_name": "New Bie"}}


@pytest.fixture
def boss(conn):
    return make_login_user(conn, "boss", "admin")


@pytest.fixture
def h(client, boss):
    return auth_header(client, "boss")


def group_id(conn, name):
    return conn.execute(text("SELECT id FROM access_group WHERE name=:n"), {"n": name}).scalar_one()


def create(client, h, **over):
    return client.post("/users", json={**NEW, **over}, headers=h)


# ---- create --------------------------------------------------------------------------------


def test_create_user_with_new_contact_groups_and_login(client, h, boss, conn):
    r = create(
        client,
        h,
        group_ids=[group_id(conn, "agent")],
        contact={
            "first_name": "New",
            "last_name": "Bie",
            "email": "n@example.com",
            "phones": [{"phone": "09171234567", "is_primary": True}],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["owner_id"] == boss and body["is_active"] is True
    assert body["name"] == "New Bie" and body["email"] == "n@example.com"
    assert body["phones"][0]["phone"] == "+639171234567"
    assert [g["name"] for g in body["groups"]] == ["agent"]
    assert "password" not in body and "password_hash" not in body
    # the new user can log in, and the contact is owned by the creator
    assert (
        client.post(
            "/auth/login", json={"username": "newbie", "password": NEW["password"]}
        ).status_code
        == 200
    )
    owner = conn.execute(
        text("SELECT owner_id FROM contacts WHERE id=:c"), {"c": body["contact_id"]}
    ).scalar_one()
    assert owner == boss


def test_create_user_linking_existing_contact_keeps_its_owner(client, h, conn):
    cid = make_contact(conn, "Existing", owner_id=1)
    r = client.post(
        "/users",
        headers=h,
        json={"username": "linked", "password": NEW["password"], "contact_id": cid},
    )
    assert r.status_code == 201, r.text
    assert r.json()["contact_id"] == cid and r.json()["name"] == "Existing"
    assert (
        conn.execute(text("SELECT owner_id FROM contacts WHERE id=:c"), {"c": cid}).scalar_one()
        == 1
    )


def test_create_needs_exactly_one_of_contact_and_contact_id(client, h, conn):
    cid = make_contact(conn, "X")
    base = {"username": "u1", "password": NEW["password"]}
    assert client.post("/users", json=base, headers=h).status_code == 422
    both = {**base, "contact_id": cid, "contact": {"first_name": "Y"}}
    assert client.post("/users", json=both, headers=h).status_code == 422


def test_create_validation(client, h):
    assert create(client, h, password="short").status_code == 422
    assert create(client, h, username="").status_code == 422
    assert create(client, h, username="x" * 65).status_code == 422
    assert create(client, h, contact_id=99999, contact=None).status_code == 404
    assert create(client, h, group_ids=[99999]).status_code == 422


def test_duplicate_username_is_409_and_reusable_after_soft_delete(client, h):
    uid = create(client, h).json()["id"]
    assert create(client, h, contact={"first_name": "Other"}).status_code == 409
    assert client.delete(f"/users/{uid}", headers=h).status_code == 204
    assert create(client, h, contact={"first_name": "Other"}).status_code == 201


def test_contact_already_linked_is_409(client, h, conn):
    body = create(client, h).json()
    r = client.post(
        "/users",
        headers=h,
        json={"username": "second", "password": NEW["password"], "contact_id": body["contact_id"]},
    )
    assert r.status_code == 409


def test_failed_create_leaves_no_orphan_contact(client, h, conn):
    create(client, h)
    before = conn.execute(text("SELECT COUNT(*) FROM contacts")).scalar_one()
    assert create(client, h, contact={"first_name": "Orphan?"}).status_code == 409  # duplicate username
    assert conn.execute(text("SELECT COUNT(*) FROM contacts")).scalar_one() == before


def test_phone_conflict_on_create_is_409(client, h, conn):
    make_phone(conn, make_contact(conn, "Holder"), "+639171234567")
    r = create(client, h, contact={"first_name": "N", "phones": [{"phone": "+639171234567"}]})
    assert r.status_code == 409


# ---- escalation and permissions on create --------------------------------------------------


def test_cannot_assign_group_beyond_own_permissions(client, conn):
    me = make_login_user(conn, "limited")
    make_group_with(
        conn,
        me,
        "users_only",
        ("users", "create"),
        ("users", "read_all"),
        ("contacts", "create"),
        ("contacts", "read_all"),
    )
    h = auth_header(client, "limited")
    assert create(client, h, group_ids=[group_id(conn, "contacts_viewer")]).status_code == 201
    r = create(
        client, h, username="u2", contact={"first_name": "U2"}, group_ids=[group_id(conn, "admin")]
    )
    assert r.status_code == 403
    assert client.get("/users?q=u2", headers=h).json()["total"] == 0


def test_new_contact_requires_contacts_create(client, conn):
    make_login_user(conn, "usersonly", "users_admin")
    h = auth_header(client, "usersonly")
    assert create(client, h).status_code == 403
    cid = make_contact(conn, "Linkable")
    # linking an existing contact needs contacts read access too
    r = client.post(
        "/users", headers=h, json={"username": "u3", "password": NEW["password"], "contact_id": cid}
    )
    assert r.status_code == 403


@pytest.mark.parametrize("role", ["operator", "agent", "auditor"])
def test_roles_without_users_create_are_forbidden(client, conn, role):
    make_login_user(conn, "r", role)
    assert create(client, auth_header(client, "r")).status_code == 403


# ---- read / list ---------------------------------------------------------------------------


def test_list_hides_system_agents_and_paginates(client, h, conn):
    make_inbound_agent(conn)
    for n in ("alpha", "beta", "gamma"):
        create(client, h, username=n, contact={"first_name": n.title()})
    body = client.get("/users?page_size=100", headers=h).json()
    names = [u["username"] for u in body["items"]]
    assert "system" not in names and "notification" not in names and "gsm-test" not in names
    assert body["total"] == len(names) == 4  # boss + 3
    page = client.get("/users?page=2&page_size=3&sort=username", headers=h).json()
    assert [u["username"] for u in page["items"]] == ["gamma"] and page["total"] == 4


def test_list_search_and_active_filter_and_sort(client, h):
    create(client, h, username="zoe", contact={"first_name": "Zoë Quill"})
    uid = create(client, h, username="mia", contact={"first_name": "Mia"}).json()["id"]
    client.put(f"/users/{uid}", json={"is_active": False}, headers=h)
    q = lambda s: [u["username"] for u in client.get(f"/users?{s}", headers=h).json()["items"]]
    assert q("q=Quill") == ["zoe"] and q("q=zo") == ["zoe"]
    assert q("is_active=false") == ["mia"]
    assert q("is_active=true&sort=username&order=desc") == ["zoe", "boss"]
    assert client.get("/users?sort=password_hash", headers=h).status_code == 422


def test_get_user_and_system_agents_are_404(client, h, conn):
    body = create(client, h).json()
    assert client.get(f"/users/{body['id']}", headers=h).json() == body
    assert client.get("/users/1", headers=h).status_code == 404  # the system agent
    assert client.get("/users/99999", headers=h).status_code == 404


def test_viewer_roles_can_read_but_not_write_users(client, conn, h):
    uid = create(client, h).json()["id"]
    for role in ("operator", "auditor"):
        make_login_user(conn, role, role)
        hh = auth_header(client, role)
        assert client.get(f"/users/{uid}", headers=hh).status_code == 200
        assert client.put(f"/users/{uid}", json={"is_active": False}, headers=hh).status_code == 403
        assert client.delete(f"/users/{uid}", headers=hh).status_code == 403


def test_agent_role_has_no_users_access(client, conn):
    make_login_user(conn, "ag", "agent")
    hh = auth_header(client, "ag")
    assert client.get("/users", headers=hh).status_code == 403
    assert client.get("/users/1", headers=hh).status_code == 403


def test_read_own_user_sees_only_users_they_created(client, conn):
    me = make_login_user(conn, "creator")
    make_group_with(
        conn,
        me,
        "own_users",
        ("users", "create"),
        ("users", "read_own"),
        ("users", "update"),
        ("users", "delete"),
        ("contacts", "create"),
    )
    h = auth_header(client, "creator")
    mine = create(client, h).json()["id"]
    body = client.get("/users", headers=h).json()
    assert [u["id"] for u in body["items"]] == [mine] and body["total"] == 1
    other = make_login_user(conn, "other", "agent")
    assert client.get(f"/users/{other}", headers=h).status_code == 404
    assert client.put(f"/users/{other}", json={"is_active": False}, headers=h).status_code == 404
    assert client.delete(f"/users/{other}", headers=h).status_code == 404


# ---- update --------------------------------------------------------------------------------


def test_update_username_active_and_groups(client, h, conn):
    uid = create(client, h, group_ids=[group_id(conn, "agent")]).json()["id"]
    r = client.put(
        f"/users/{uid}",
        headers=h,
        json={"username": "renamed", "is_active": False, "group_ids": [group_id(conn, "auditor")]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["username"] == "renamed" and body["is_active"] is False
    assert [g["name"] for g in body["groups"]] == ["auditor"]
    # a deactivated user can no longer log in
    login = client.post("/auth/login", json={"username": "renamed", "password": NEW["password"]})
    assert login.status_code == 401


def test_update_omitted_fields_unchanged_and_empty_groups_clears(client, h, conn):
    uid = create(client, h, group_ids=[group_id(conn, "agent")]).json()["id"]
    assert client.put(f"/users/{uid}", json={}, headers=h).json()["groups"]
    assert client.put(f"/users/{uid}", json={"group_ids": []}, headers=h).json()["groups"] == []


def test_update_duplicate_username_409(client, h):
    create(client, h, username="taken")
    uid = create(client, h, username="free", contact={"first_name": "F"}).json()["id"]
    assert client.put(f"/users/{uid}", json={"username": "taken"}, headers=h).status_code == 409


def test_update_cannot_assign_group_beyond_own(client, conn):
    me = make_login_user(conn, "limited")
    make_group_with(
        conn,
        me,
        "um",
        ("users", "create"),
        ("users", "read_all"),
        ("users", "update"),
        ("contacts", "create"),
    )
    h = auth_header(client, "limited")
    uid = create(client, h).json()["id"]
    r = client.put(f"/users/{uid}", json={"group_ids": [group_id(conn, "admin")]}, headers=h)
    assert r.status_code == 403


def test_update_contact_fields_goes_through_contacts_permission(client, h, conn):
    uid = create(client, h).json()["id"]
    r = client.put(
        f"/users/{uid}",
        headers=h,
        json={"first_name": "Renamed", "email": "r@example.com", "phones": [{"phone": "+639171234567"}]},
    )
    assert r.status_code == 200, r.text
    assert (r.json()["name"], r.json()["email"], r.json()["phones"][0]["phone"]) == (
        "Renamed",
        "r@example.com",
        "+639171234567",
    )
    assert client.put(f"/users/{uid}", json={"email": None}, headers=h).json()["email"] is None
    # users_admin alone holds no contacts permission, so it can change the user but not the name
    make_login_user(conn, "ua", "users_admin")
    ha = auth_header(client, "ua")
    assert client.put(f"/users/{uid}", json={"is_active": True}, headers=ha).status_code == 200
    assert client.put(f"/users/{uid}", json={"first_name": "Hacked"}, headers=ha).status_code == 403


def test_cannot_deactivate_or_delete_yourself(client, h, boss):
    assert client.put(f"/users/{boss}", json={"is_active": False}, headers=h).status_code == 409
    assert client.delete(f"/users/{boss}", headers=h).status_code == 409
    assert client.put(f"/users/{boss}", json={"username": "boss2"}, headers=h).status_code == 200


# ---- delete --------------------------------------------------------------------------------


def test_delete_soft_deletes_user_keeps_contact_and_blocks_login(client, h, conn):
    body = create(client, h).json()
    assert client.delete(f"/users/{body['id']}", headers=h).status_code == 204
    assert client.get(f"/users/{body['id']}", headers=h).status_code == 404
    assert client.delete(f"/users/{body['id']}", headers=h).status_code == 404
    assert client.get(f"/contacts/{body['contact_id']}", headers=h).status_code == 200
    assert (
        client.post(
            "/auth/login", json={"username": "newbie", "password": NEW["password"]}
        ).status_code
        == 401
    )
    # now the contact can be deleted, since no active user is linked
    assert client.delete(f"/contacts/{body['contact_id']}", headers=h).status_code == 204


def test_delete_revokes_refresh_tokens(client, h, conn):
    create(client, h)
    tokens = client.post(
        "/auth/login", json={"username": "newbie", "password": NEW["password"]}
    ).json()
    uid = client.get("/users?q=newbie", headers=h).json()["items"][0]["id"]
    client.delete(f"/users/{uid}", headers=h)
    assert (
        client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code
        == 401
    )


def test_unauthenticated(client):
    for call in (
        client.get("/users"),
        client.post("/users", json=NEW),
        client.get("/users/1"),
        client.put("/users/1", json={}),
        client.delete("/users/1"),
    ):
        assert call.status_code == 401
