import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Base, Contact, User
from tests.db.helpers import make_contact, soft_delete


def test_models_match_the_migrated_schema(engine):
    """Autogenerate must find nothing to change: models and migrations cannot drift apart."""
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == []


@pytest.fixture
def session(conn):
    with Session(bind=conn) as s:
        yield s


def test_orm_queries_hide_soft_deleted_rows_by_default(conn, session):
    keep = make_contact(conn, "Keep")
    gone = make_contact(conn, "Gone")
    soft_delete(conn, "contacts", gone)

    visible = {c.id for c in session.scalars(select(Contact))}
    assert keep in visible and gone not in visible


def test_include_deleted_option_shows_soft_deleted_rows(conn, session):
    gone = make_contact(conn, "Gone")
    soft_delete(conn, "contacts", gone)

    everything = {
        c.id for c in session.scalars(select(Contact).execution_options(include_deleted=True))
    }
    assert gone in everything


def test_filter_applies_to_every_soft_deletable_model(conn, session):
    assert session.scalars(select(User).where(User.id == 1)).one().username == "system"
    from tests.db.helpers import make_user

    u = make_user(conn, "temp")
    soft_delete(conn, "users", u)
    assert session.get(User, u) is None or session.scalars(select(User).where(User.id == u)).all() == []
