from sqlalchemy import text

SYSTEM_USER_ID = 1


def insert(conn, table: str, **cols) -> int:
    names = ", ".join(f"`{c}`" for c in cols)
    params = ", ".join(f":{c}" for c in cols)
    result = conn.execute(text(f"INSERT INTO `{table}` ({names}) VALUES ({params})"), cols)
    return result.lastrowid


def make_contact(conn, name="Someone", owner_id=SYSTEM_USER_ID, **cols) -> int:
    """``name`` goes whole into ``first_name`` (``contacts.name`` is generated from the parts)."""
    cols.setdefault("type", "person")
    cols.setdefault("first_name", name)
    return insert(conn, "contacts", owner_id=owner_id, **cols)


def make_user(conn, username, contact_id=None, owner_id=SYSTEM_USER_ID, **cols) -> int:
    if contact_id is None:
        contact_id = make_contact(conn, name=username, owner_id=owner_id)
    return insert(conn, "users", username=username, contact_id=contact_id, owner_id=owner_id, **cols)


def make_phone(conn, contact_id, number="+639171234567", **cols) -> int:
    return insert(conn, "contact_phone", contact_id=contact_id, phone_e164=number, **cols)


def make_message(conn, contact_id, owner_id=SYSTEM_USER_ID, **cols) -> int:
    cols.setdefault("channel", "gsm")
    cols.setdefault("phone_number", "+639171234567")
    cols.setdefault("content", "hello")
    cols.setdefault("status", "queued")
    return insert(conn, "messages", contact_id=contact_id, owner_id=owner_id, **cols)


def soft_delete(conn, table: str, row_id: int) -> None:
    conn.execute(text(f"UPDATE `{table}` SET deleted_at = NOW() WHERE id = :i"), {"i": row_id})


def add_to_groups(conn, user_id: int, *group_names: str) -> None:
    for name in group_names:
        group_id = conn.execute(
            text("SELECT id FROM access_group WHERE name = :n"), {"n": name}
        ).scalar_one()
        insert(conn, "user_group", user_id=user_id, group_id=group_id)


def make_login_user(conn, username, *groups, password="correct horse battery", **cols) -> int:
    from app.security import hash_password

    user_id = make_user(conn, username, password_hash=hash_password(password), **cols)
    add_to_groups(conn, user_id, *groups)
    return user_id


def make_inbound_agent(conn, username="gsm-test") -> int:
    contact_id = make_contact(conn, username, type="entity")
    return insert(conn, "users", username=username, contact_id=contact_id,
                  owner_id=SYSTEM_USER_ID, is_system=1, agent_direction="inbound",
                  login_enabled=0)


def make_group_with(conn, user_id: int, name: str, *perms: tuple[str, str]) -> int:
    """A throwaway group holding exactly ``perms``, assigned to the user."""
    gid = insert(conn, "access_group", name=name, owner_id=SYSTEM_USER_ID, is_system=0)
    insert(conn, "group_closure", ancestor_id=gid, descendant_id=gid)
    for resource, action in perms:
        pid = conn.execute(
            text("SELECT id FROM permission WHERE resource = :r AND action = :a"),
            {"r": resource, "a": action},
        ).scalar_one()
        insert(conn, "group_permission", group_id=gid, permission_id=pid)
    insert(conn, "user_group", user_id=user_id, group_id=gid)
    return gid
