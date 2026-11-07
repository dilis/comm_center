import pytest

from tests.api.conftest import auth_header
from tests.db.helpers import make_login_user, soft_delete

pytestmark = pytest.mark.db


def test_admin_lists_groups_with_effective_permissions(client, conn):
    make_login_user(conn, "boss", "admin")
    r = client.get("/groups?page_size=100", headers=auth_header(client, "boss"))
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"items", "total", "page", "page_size"}
    assert body["total"] == 13  # 9 building blocks + 4 roles
    by_name = {g["name"]: g for g in body["items"]}
    assert by_name["contacts_viewer"]["permissions"] == ["contacts:read_all"]
    # roles include their descendants' permissions
    assert "messages:delete" in by_name["admin"]["permissions"]
    assert [g["name"] for g in body["items"]] == sorted(by_name)


def test_groups_pagination(client, conn):
    make_login_user(conn, "boss", "admin")
    r = client.get("/groups?page=2&page_size=5", headers=auth_header(client, "boss"))
    body = r.json()
    assert len(body["items"]) == 5 and body["total"] == 13 and body["page"] == 2


@pytest.mark.parametrize("role", ["operator", "agent", "auditor"])
def test_other_roles_cannot_list_groups(client, conn, role):
    make_login_user(conn, "someone", role)
    assert client.get("/groups", headers=auth_header(client, "someone")).status_code == 403


def test_groups_require_auth(client):
    assert client.get("/groups").status_code == 401


def test_deleted_groups_are_hidden(client, conn):
    make_login_user(conn, "boss", "admin")
    from sqlalchemy import text

    gid = conn.execute(text("SELECT id FROM access_group WHERE name='auditor'")).scalar_one()
    soft_delete(conn, "access_group", gid)
    body = client.get("/groups?page_size=100", headers=auth_header(client, "boss")).json()
    assert body["total"] == 12 and "auditor" not in {g["name"] for g in body["items"]}


def test_page_size_is_bounded(client, conn):
    make_login_user(conn, "boss", "admin")
    h = auth_header(client, "boss")
    assert client.get("/groups?page_size=0", headers=h).status_code == 422
    assert client.get("/groups?page_size=101", headers=h).status_code == 422
    assert client.get("/groups?page=0", headers=h).status_code == 422
