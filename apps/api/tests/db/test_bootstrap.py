import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import security
from app.authz import effective_permissions
from app.bootstrap import BootstrapError, create_admin
from app.models import Contact, User
from tests.db.helpers import make_login_user


@pytest.fixture
def session(conn):
    with Session(bind=conn, join_transaction_mode="create_savepoint") as s:
        yield s


def test_create_admin_makes_a_working_admin(session):
    user = create_admin(session, "root", "a long enough passphrase", "Root Admin")
    assert security.verify_password(user.password_hash, "a long enough passphrase")
    assert user.owner_id == 1 and user.is_system is False and user.login_enabled is True
    contact = session.get(Contact, user.contact_id)
    assert (contact.name, contact.type, contact.owner_id) == ("Root Admin", "person", 1)
    assert ("users", "create") in effective_permissions(session, user.id)
    assert ("groups", "read_all") in effective_permissions(session, user.id)


def test_create_admin_refuses_a_short_password(session):
    with pytest.raises(BootstrapError, match="at least"):
        create_admin(session, "root", "short", "Root")
    assert session.scalars(select(User).where(User.username == "root")).first() is None


def test_create_admin_refuses_once_a_human_user_exists(conn, session):
    make_login_user(conn, "existing", "agent")
    with pytest.raises(BootstrapError, match="already exists"):
        create_admin(session, "root", "a long enough passphrase", "Root")
