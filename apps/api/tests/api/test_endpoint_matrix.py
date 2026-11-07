"""Seed role x Phase 3 endpoint: the status each role gets, written out by hand from SPECS.md 4.6.

Write calls target a row the caller can see (so a 403 is the permission, not a 404). 'ok' means the
request passes authorization; the exact success code is covered in the per-resource test files.
"""

import pytest

from tests.api.conftest import auth_header
from tests.db.helpers import make_contact, make_login_user

pytestmark = pytest.mark.db

ROLES = ("admin", "operator", "agent", "auditor")

# endpoint -> roles allowed through
ALLOWED = {
    "GET /contacts": {"admin", "operator", "agent", "auditor"},
    "POST /contacts": {"admin", "operator"},
    "GET /contacts/{c}": {"admin", "operator", "agent", "auditor"},
    "PUT /contacts/{c}": {"admin", "operator"},
    "DELETE /contacts/{c}": {"admin"},
    "GET /users": {"admin", "operator", "auditor"},
    "POST /users": {"admin"},
    "GET /users/{u}": {"admin", "operator", "auditor"},
    "PUT /users/{u}": {"admin"},
    "DELETE /users/{u}": {"admin"},
    "GET /groups": {"admin"},
}


def call(client, endpoint, headers, contact_id, user_id):
    method, path = endpoint.split(" ")
    path = path.replace("{c}", str(contact_id)).replace("{u}", str(user_id))
    body = None
    if endpoint == "POST /contacts":
        body = {"name": "New"}
    elif endpoint == "PUT /contacts/{c}":
        body = {"name": "Renamed"}
    elif endpoint == "POST /users":
        body = {"username": "fresh", "password": "a long enough pass", "contact": {"name": "Fresh"}}
    elif endpoint == "PUT /users/{u}":
        body = {"is_active": True}
    return client.request(method, path, headers=headers, json=body)


@pytest.mark.parametrize("endpoint", sorted(ALLOWED))
@pytest.mark.parametrize("role", ROLES)
def test_role_against_endpoint(client, conn, role, endpoint):
    make_login_user(conn, "caller", role)
    victim_user = make_login_user(conn, "victim", "agent")
    victim_contact = make_contact(conn, "Victim contact")
    r = call(client, endpoint, auth_header(client, "caller"), victim_contact, victim_user)
    if role in ALLOWED[endpoint]:
        assert r.status_code < 400, (role, endpoint, r.status_code, r.text)
    else:
        assert r.status_code == 403, (role, endpoint, r.status_code, r.text)
