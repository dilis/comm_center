"""Seed role x Phase 3 endpoint: the status each role gets, written out by hand from SPECS.md 4.6.

Write calls target a row the caller can see (so a 403 is the permission, not a 404). 'ok' means the
request passes authorization; the exact success code is covered in the per-resource test files.
"""

import pytest

from tests.api.conftest import auth_header
from tests.db.helpers import (
    make_contact,
    make_inbound_agent,
    make_login_user,
    make_message,
    make_phone,
)

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
    "GET /messages": {"admin", "operator", "agent", "auditor"},
    "GET /messages/counts": {"admin", "operator", "agent", "auditor"},
    "POST /messages/send": {"admin", "operator", "agent"},
    "POST /messages/send-bulk": {"admin", "operator", "agent"},
    "GET /messages/{m}": {"admin", "operator", "agent", "auditor"},
    "DELETE /messages/{m}": {"admin"},
}


def call(client, endpoint, headers, contact_id, user_id, message_id):
    method, path = endpoint.split(" ")
    path = (
        path.replace("{c}", str(contact_id))
        .replace("{u}", str(user_id))
        .replace("{m}", str(message_id))
    )
    body = None
    if endpoint == "POST /contacts":
        body = {"name": "New"}
    elif endpoint == "PUT /contacts/{c}":
        body = {"name": "Renamed"}
    elif endpoint == "POST /users":
        body = {"username": "fresh", "password": "a long enough pass", "contact": {"name": "Fresh"}}
    elif endpoint == "POST /messages/send":
        body = {"contact_id": contact_id, "content": "hi"}
    elif endpoint == "POST /messages/send-bulk":
        body = {"contact_ids": [contact_id], "content": "hi"}
    elif endpoint == "PUT /users/{u}":
        body = {"is_active": True}
    return client.request(method, path, headers=headers, json=body)


@pytest.mark.parametrize("endpoint", sorted(ALLOWED))
@pytest.mark.parametrize("role", ROLES)
def test_role_against_endpoint(client, conn, role, endpoint):
    make_login_user(conn, "caller", role)
    victim_user = make_login_user(conn, "victim", "agent")
    victim_contact = make_contact(conn, "Victim contact")
    make_phone(conn, victim_contact, "+639171234567")
    # inbound, so all four roles can read it and a 403 can only be the permission
    message = make_message(conn, victim_contact, owner_id=make_inbound_agent(conn))
    r = call(client, endpoint, auth_header(client, "caller"), victim_contact, victim_user, message)
    if role in ALLOWED[endpoint]:
        assert r.status_code < 400, (role, endpoint, r.status_code, r.text)
    else:
        assert r.status_code == 403, (role, endpoint, r.status_code, r.text)
