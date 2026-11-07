"""Writing the planned contacts to the database (rolled back after each test)."""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from scripts.import_contacts import ImportProblem, Row, apply, plan, resolve_owner
from tests.db.helpers import make_contact, make_login_user, make_phone, soft_delete


@pytest.fixture
def db(conn):
    with Session(bind=conn, join_transaction_mode="create_savepoint") as session:
        yield session


@pytest.fixture
def owner(conn):
    return make_login_user(conn, "importer", "admin")


def planned(*pairs):
    return plan([Row(i + 2, name, phone) for i, (name, phone) in enumerate(pairs)])


def contacts(db):
    return db.execute(
        text(
            "SELECT c.name, c.type, c.owner_id, p.phone_e164, p.is_primary FROM contacts c "
            "JOIN contact_phone p ON p.contact_id = c.id WHERE c.id > 1 ORDER BY c.id"
        )
    ).all()


def test_each_planned_contact_becomes_a_person_with_one_primary_phone(db, owner):
    result = apply(db, planned(("Ana Cruz", 639171234567), ("Ben Lim", 639181234567)), owner)
    db.commit()
    assert result.created == 2 and result.existing == []
    rows = [
        r
        for r in contacts(db)
        if r.phone_e164.startswith("+63917") or r.phone_e164.startswith("+63918")
    ]
    assert [(r.name, r.type, r.owner_id, r.phone_e164, r.is_primary) for r in rows] == [
        ("Ana Cruz", "person", owner, "+639171234567", 1),
        ("Ben Lim", "person", owner, "+639181234567", 1),
    ]


def test_numbers_that_already_exist_are_skipped_and_never_overwritten(db, conn, owner):
    existing = make_contact(conn, "Original Name")
    make_phone(conn, existing, "+639171234567")
    result = apply(db, planned(("Ana Cruz", 639171234567), ("Ben Lim", 639181234567)), owner)
    db.commit()
    assert result.created == 1
    assert [(e.phone, e.name) for e in result.existing] == [("+639171234567", "Original Name")]
    assert (
        db.execute(text("SELECT name FROM contacts WHERE id = :i"), {"i": existing}).scalar_one()
        == "Original Name"
    )
    assert (
        db.execute(
            text("SELECT COUNT(*) FROM contact_phone WHERE phone_e164='+639171234567'")
        ).scalar_one()
        == 1
    )


def test_running_it_twice_changes_nothing_the_second_time(db, owner):
    first = apply(db, planned(("Ana Cruz", 639171234567)), owner)
    db.commit()
    second = apply(db, planned(("Ana Cruz", 639171234567)), owner)
    db.commit()
    assert (first.created, second.created, len(second.existing)) == (1, 0, 1)


def test_a_deleted_contacts_number_gets_a_new_contact(db, conn, owner):
    old = make_contact(conn, "Old")
    phone = make_phone(conn, old, "+639171234567")
    soft_delete(conn, "contact_phone", phone)
    soft_delete(conn, "contacts", old)
    result = apply(db, planned(("Ana Cruz", 639171234567)), owner)
    db.commit()
    assert result.created == 1


def test_nothing_is_written_until_the_caller_commits(db, owner):
    apply(db, planned(("Ana Cruz", 639171234567)), owner)
    db.rollback()  # what --dry-run does
    assert contacts(db) == []


def test_owner_must_be_an_active_human_user(db, conn, owner):
    assert resolve_owner(db, "importer") == owner
    with pytest.raises(ImportProblem, match="no user"):
        resolve_owner(db, "nobody")
    with pytest.raises(ImportProblem, match="no user"):
        resolve_owner(db, "system")  # a system agent cannot own imports
    conn.execute(text("UPDATE users SET is_active = 0 WHERE id = :i"), {"i": owner})
    with pytest.raises(ImportProblem, match="inactive"):
        resolve_owner(db, "importer")
