import pytest
from sqlalchemy.exc import DBAPIError

from tests.db.helpers import make_contact, make_phone, soft_delete


@pytest.mark.parametrize("bad", ["0171234567", "+0123456", "12345", "+12", "+63 917 123 4567", "abc"])
def test_phone_must_be_e164(conn, bad):
    contact = make_contact(conn)
    with pytest.raises(DBAPIError, match="ck_contact_phone_e164"):
        make_phone(conn, contact, bad)


def test_valid_e164_numbers_are_accepted(conn):
    contact = make_contact(conn)
    make_phone(conn, contact, "+639171234567")
    make_phone(conn, contact, "+14155552671")


def test_active_phone_numbers_are_globally_unique(conn):
    make_phone(conn, make_contact(conn, "A"), "+639170000001")
    with pytest.raises(DBAPIError, match="uq_contact_phone_active_phone"):
        make_phone(conn, make_contact(conn, "B"), "+639170000001")


def test_phone_is_reusable_after_its_row_is_soft_deleted(conn):
    first = make_phone(conn, make_contact(conn, "A"), "+639170000002")
    soft_delete(conn, "contact_phone", first)
    make_phone(conn, make_contact(conn, "B"), "+639170000002")


def test_a_contact_has_at_most_one_active_primary_number(conn):
    contact = make_contact(conn)
    make_phone(conn, contact, "+639170000003", is_primary=1)
    make_phone(conn, contact, "+639170000004", is_primary=0)
    make_phone(conn, contact, "+639170000005", is_primary=0)
    with pytest.raises(DBAPIError, match="uq_contact_phone_active_primary"):
        make_phone(conn, contact, "+639170000006", is_primary=1)


def test_a_new_primary_is_allowed_after_the_old_one_is_deleted(conn):
    contact = make_contact(conn)
    old = make_phone(conn, contact, "+639170000007", is_primary=1)
    soft_delete(conn, "contact_phone", old)
    make_phone(conn, contact, "+639170000008", is_primary=1)


def test_different_contacts_can_each_have_a_primary(conn):
    make_phone(conn, make_contact(conn, "A"), "+639170000009", is_primary=1)
    make_phone(conn, make_contact(conn, "B"), "+639170000010", is_primary=1)
