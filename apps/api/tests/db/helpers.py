from sqlalchemy import text

SYSTEM_USER_ID = 1


def insert(conn, table: str, **cols) -> int:
    names = ", ".join(f"`{c}`" for c in cols)
    params = ", ".join(f":{c}" for c in cols)
    result = conn.execute(text(f"INSERT INTO `{table}` ({names}) VALUES ({params})"), cols)
    return result.lastrowid


def make_contact(conn, name="Someone", owner_id=SYSTEM_USER_ID, **cols) -> int:
    cols.setdefault("type", "person")
    return insert(conn, "contacts", name=name, owner_id=owner_id, **cols)


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
