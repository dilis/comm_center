"""Permission matrix: every seed role against every (resource, action) and read scope.

Expected values are written out by hand from SPECS.md 4.6, not derived from the seed, so a wrong
seed or a wrong resolver both fail here. A probe app exposes ``require`` and ``scope`` the way the
Phase 3/4 endpoints will use them.
"""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.authz import AuthUser, require, scope
from app.db import get_db
from app.deps import get_current_user
from app.models import Contact, Message
from tests.api.conftest import auth_header
from tests.db.helpers import (
    make_contact,
    make_group_with,
    make_inbound_agent,
    make_login_user,
    make_message,
    soft_delete,
)

ROLES = ("admin", "operator", "agent", "auditor")
CRUD = ("create", "read_all", "read_own", "update", "delete")

# role -> {resource: allowed actions}
EXPECTED = {
    "admin": {
        "users": {"create", "read_all", "update", "delete"},
        "contacts": {"create", "read_all", "update", "delete"},
        "messages": {"create", "read_all", "delete"},
        "groups": {"read_all"},
    },
    "operator": {
        "users": {"read_all"},
        "contacts": {"create", "read_all", "update"},
        "messages": {"create", "read_all"},
        "groups": set(),
    },
    "agent": {
        "users": set(),
        "contacts": {"read_all"},
        "messages": {"create", "read_own", "read_received"},
        "groups": set(),
    },
    "auditor": {
        "users": {"read_all"},
        "contacts": {"read_all"},
        "messages": {"read_all"},
        "groups": set(),
    },
}
ALL_ACTIONS = {
    "users": CRUD, "contacts": CRUD, "messages": (*CRUD, "read_received"), "groups": ("read_all",),
}

probe = FastAPI()


def _register(resource: str, action: str) -> None:
    dependency = require(resource, action)

    def endpoint(user: AuthUser = Depends(dependency)):
        return {"ok": True}

    probe.add_api_route(f"/require/{resource}/{action}", endpoint, methods=["GET"])


for _res, _acts in ALL_ACTIONS.items():
    for _act in _acts:
        _register(_res, _act)


@probe.get("/scope/messages")
def scope_messages(user: AuthUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return sorted(db.scalars(scope(select(Message.id), user, "messages")))


@probe.get("/scope/contacts")
def scope_contacts(user: AuthUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return sorted(db.scalars(scope(select(Contact.id), user, "contacts")))


@pytest.fixture
def pclient(db):
    probe.dependency_overrides[get_db] = lambda: db
    yield TestClient(probe)
    probe.dependency_overrides.clear()


@pytest.fixture
def people(conn):
    return {role: make_login_user(conn, f"u_{role}", role) for role in ROLES}


@pytest.fixture
def headers_for(client):
    """Tokens come from the real app's /auth/login (the ``client`` fixture), same database."""
    return lambda username: auth_header(client, username)


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("resource", sorted(ALL_ACTIONS))
def test_require_matrix(pclient, people, headers_for, role, resource):
    headers = headers_for(f"u_{role}")
    for action in ALL_ACTIONS[resource]:
        status = pclient.get(f"/require/{resource}/{action}", headers=headers).status_code
        expected = 200 if action in EXPECTED[role][resource] else 403
        assert status == expected, f"{role} {resource}:{action}"


def test_require_without_a_token_is_401(pclient):
    assert pclient.get("/require/users/read_all").status_code == 401


@pytest.fixture
def messages(conn, people):
    """One message per ownership class, keyed by a readable name."""
    peer = make_contact(conn, "Peer")
    gsm_agent = make_inbound_agent(conn)
    notification = conn.execute(
        text("SELECT id FROM users WHERE username = 'notification'")
    ).scalar_one()
    return {
        "agent_sent": make_message(conn, peer, owner_id=people["agent"]),
        "operator_sent": make_message(conn, peer, owner_id=people["operator"]),
        "admin_sent": make_message(conn, peer, owner_id=people["admin"]),
        "inbound": make_message(conn, peer, owner_id=gsm_agent, status="received"),
        "notification": make_message(conn, peer, owner_id=notification),
    }


EVERYTHING = {"agent_sent", "operator_sent", "admin_sent", "inbound", "notification"}


@pytest.mark.parametrize(
    "role, visible",
    [
        ("admin", EVERYTHING),
        ("operator", EVERYTHING),
        ("auditor", EVERYTHING),
        ("agent", {"agent_sent", "inbound"}),  # own + received; not others' or notifications
    ],
)
def test_message_scope_matrix(pclient, headers_for, messages, people, role, visible):
    ids = pclient.get("/scope/messages", headers=headers_for(f"u_{role}")).json()
    assert ids == sorted(messages[name] for name in visible)


def test_deleted_messages_stay_out_of_scope(pclient, conn, headers_for, people, messages):
    soft_delete(conn, "messages", messages["inbound"])
    ids = pclient.get("/scope/messages", headers=headers_for("u_agent")).json()
    assert messages["inbound"] not in ids


def test_read_received_alone_sees_only_inbound(pclient, conn, headers_for, messages):
    uid = make_login_user(conn, "recv_only")
    make_group_with(conn, uid, "recv_only_grp", ("messages", "read_received"))
    assert pclient.get("/scope/messages", headers=headers_for("recv_only")).json() == [
        messages["inbound"]
    ]


def test_read_own_alone_sees_only_own(pclient, conn, headers_for, messages, people):
    uid = make_login_user(conn, "own_msgs")
    make_group_with(conn, uid, "own_msgs_grp", ("messages", "read_own"))
    mine = make_message(conn, make_contact(conn, "P"), owner_id=uid)
    assert pclient.get("/scope/messages", headers=headers_for("own_msgs")).json() == [mine]


def test_no_message_read_permission_is_403(pclient, conn, headers_for):
    make_login_user(conn, "contacts_only", "contacts_viewer")
    assert pclient.get("/scope/messages", headers=headers_for("contacts_only")).status_code == 403


def test_contacts_read_all_vs_read_own(pclient, conn, headers_for, people):
    mine = make_contact(conn, "Mine", owner_id=people["agent"])
    other = make_contact(conn, "Other", owner_id=people["admin"])
    assert {mine, other} <= set(pclient.get("/scope/contacts", headers=headers_for("u_admin")).json())

    uid = make_login_user(conn, "own_only")
    make_group_with(conn, uid, "own_only_grp", ("contacts", "read_own"))
    own = make_contact(conn, "Own", owner_id=uid)
    assert pclient.get("/scope/contacts", headers=headers_for("own_only")).json() == [own]


def test_contacts_scope_without_read_permission_is_403(pclient, conn, headers_for):
    make_login_user(conn, "nothing")
    assert pclient.get("/scope/contacts", headers=headers_for("nothing")).status_code == 403
