import pytest

from tests.api.conftest import PASSWORD, auth_header, login
from tests.db.helpers import make_contact, make_login_user, make_phone, soft_delete


@pytest.fixture
def alice(conn):
    return make_login_user(conn, "alice", "agent")


@pytest.fixture
def headers(client, alice):
    return auth_header(client, "alice")


def test_update_name_and_email(client, headers):
    r = client.patch("/auth/me/profile", json={"first_name": "Alice A", "email": "a@example.com"}, headers=headers)
    assert r.status_code == 200 and r.json()["name"] == "Alice A" and r.json()["email"] == "a@example.com"
    r = client.patch("/auth/me/profile", json={"clear_email": True}, headers=headers)
    assert r.json()["email"] is None and r.json()["name"] == "Alice A"


def test_profile_rejects_bad_email_and_blank_name(client, headers):
    assert client.patch("/auth/me/profile", json={"email": "nope"}, headers=headers).status_code == 422
    assert client.patch("/auth/me/profile", json={"first_name": ""}, headers=headers).status_code == 422


def test_profile_requires_auth(client):
    assert client.patch("/auth/me/profile", json={"first_name": "x"}).status_code == 401


def test_self_service_works_without_any_contacts_or_users_permission(client, conn):
    make_login_user(conn, "bare", "messages_agent")  # holds no contacts/users permissions
    h = auth_header(client, "bare")
    assert client.patch("/auth/me/profile", json={"first_name": "Bare"}, headers=h).status_code == 200


def test_replace_phones_normalizes_and_stores(client, headers):
    r = client.put("/auth/me/phones", headers=headers, json={"phones": [
        {"phone": "0917 123 4567", "label": "mobile", "is_primary": True},
        {"phone": "+639181234567"},
    ]})
    assert r.status_code == 200
    assert r.json()["phones"] == [
        {"phone": "+639171234567", "label": "mobile", "is_primary": True},
        {"phone": "+639181234567", "label": None, "is_primary": False},
    ]


def test_replace_phones_soft_deletes_removed_and_moves_primary(client, headers):
    put = lambda phones: client.put("/auth/me/phones", headers=headers, json={"phones": phones})
    put([{"phone": "+639171234567", "is_primary": True}, {"phone": "+639181234567"}])
    r = put([{"phone": "+639181234567", "is_primary": True}])
    assert r.json()["phones"] == [{"phone": "+639181234567", "label": None, "is_primary": True}]
    # the removed number is freed for reuse
    assert put([{"phone": "+639171234567"}]).status_code == 200


def test_phone_validation_errors(client, headers):
    put = lambda phones: client.put("/auth/me/phones", headers=headers, json={"phones": phones})
    assert put([{"phone": "abc"}]).status_code == 422
    assert put([{"phone": "+639171234567"}, {"phone": "0917 123 4567"}]).status_code == 422
    assert put([{"phone": "+639171234567", "is_primary": True},
                {"phone": "+639181234567", "is_primary": True}]).status_code == 422


def test_phone_in_use_by_another_contact_is_a_409_and_changes_nothing(client, conn, headers):
    make_phone(conn, make_contact(conn, "Other"), "+639171234567")
    client.put("/auth/me/phones", headers=headers, json={"phones": [{"phone": "+639181234567"}]})
    r = client.put("/auth/me/phones", headers=headers, json={"phones": [{"phone": "+639171234567"}]})
    assert r.status_code == 409
    assert [p["phone"] for p in client.get("/auth/me", headers=headers).json()["phones"]] == ["+639181234567"]


def test_number_of_a_soft_deleted_contact_can_be_claimed(client, conn, headers):
    other = make_contact(conn, "Old")
    phone_id = make_phone(conn, other, "+639171234567")
    soft_delete(conn, "contact_phone", phone_id)
    r = client.put("/auth/me/phones", headers=headers, json={"phones": [{"phone": "+639171234567"}]})
    assert r.status_code == 200


def test_change_password(client, headers):
    old_refresh = login(client, "alice")["refresh_token"]
    r = client.put("/auth/me/password", headers=headers,
                   json={"current_password": PASSWORD, "new_password": "a brand new passphrase"})
    assert r.status_code == 204
    assert client.post("/auth/login", json={"username": "alice", "password": PASSWORD}).status_code == 401
    assert client.post("/auth/login", json={"username": "alice", "password": "a brand new passphrase"}).status_code == 200
    assert client.post("/auth/refresh", json={"refresh_token": old_refresh}).status_code == 401


def test_change_password_needs_the_current_one_and_a_long_new_one(client, headers):
    bad = client.put("/auth/me/password", headers=headers,
                     json={"current_password": "wrong wrong wrong", "new_password": "a brand new passphrase"})
    assert bad.status_code == 403
    short = client.put("/auth/me/password", headers=headers,
                       json={"current_password": PASSWORD, "new_password": "short"})
    assert short.status_code == 422
    assert client.post("/auth/login", json={"username": "alice", "password": PASSWORD}).status_code == 200
