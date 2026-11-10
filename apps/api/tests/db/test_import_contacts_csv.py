"""Writing CSV rows to the database (rolled back after each test)."""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from scripts.import_contacts_csv import CsvRow, apply, plan
from tests.db.helpers import make_contact, make_login_user, make_phone


@pytest.fixture
def db(conn):
    with Session(bind=conn, join_transaction_mode="create_savepoint") as session:
        yield session


@pytest.fixture
def owner(conn):
    return make_login_user(conn, "importer", "admin")


def row(i, first, middle, last, phone):
    return CsvRow(i + 2, first, middle, last, phone)


def stored(db):
    return db.execute(
        text(
            "SELECT c.first_name, c.middle_name, c.last_name, c.name, c.type, c.owner_id, "
            "p.phone_e164, p.is_primary FROM contacts c "
            "JOIN contact_phone p ON p.contact_id = c.id WHERE c.id > 1 ORDER BY c.id"
        )
    ).all()


def test_creates_a_person_with_the_three_name_parts_and_a_primary_number(db, owner):
    planned = plan([row(0, "Zetha Flosy", "C.", "Orpilla", "0947 711 4810"), row(1, "Caleb", "", "", "09178936000")])
    result = apply(db, planned, owner)
    assert result.created == 2
    assert [tuple(r) for r in stored(db)] == [
        ("Zetha Flosy", "C.", "Orpilla", "Zetha Flosy C. Orpilla", "person", owner, "+639477114810", 1),
        ("Caleb", None, None, "Caleb", "person", owner, "+639178936000", 1),
    ]


def test_a_number_already_in_the_database_is_left_alone(db, conn, owner):
    existing = make_contact(conn, "Old Name")
    make_phone(conn, existing, "+639171234567")
    result = apply(db, plan([row(0, "New", "", "Name", "09171234567")]), owner)
    assert result.created == 0 and result.existing == ["+639171234567"]
    assert [r.first_name for r in stored(db)] == ["Old Name"]


def test_the_email_is_saved_on_the_contact(db, conn, owner):
    apply(db, plan([CsvRow(2, "Ana", "", "Cruz", "09171234567", "ana@example.com")]), owner)
    assert db.execute(text("SELECT email FROM contacts WHERE first_name = 'Ana'")).scalar_one() == "ana@example.com"
