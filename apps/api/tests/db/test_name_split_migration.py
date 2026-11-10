"""Migration 0013 splits existing contact names into first, middle and last name."""

from sqlalchemy import create_engine, text

from alembic import command
from tests.db.conftest import ADMIN_URL, alembic_config

SCRATCH = "comm_center_namesplit"
APP_URL = "mysql+pymysql://comm_center:comm_center@127.0.0.1:3307/"

CASES = [
    # (stored name, type, first, middle, last)
    ("Ana", "person", "Ana", None, None),
    ("Ana Cruz", "person", "Ana", None, "Cruz"),
    ("Ana Maria Cruz", "person", "Ana", "Maria", "Cruz"),
    ("  Ana   Maria  Luisa   Cruz ", "person", "Ana", "Maria Luisa", "Cruz"),
    ("Acme Trading Inc", "entity", "Acme Trading Inc", None, None),
    ("+639171234567", "person", "+639171234567", None, None),
]


def test_existing_names_are_split_and_the_generated_name_is_kept():
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {SCRATCH}"))
        c.execute(text(f"CREATE DATABASE {SCRATCH} CHARACTER SET utf8mb4"))
        c.execute(text(f"GRANT ALL ON {SCRATCH}.* TO 'comm_center'@'%'"))
    url = APP_URL + SCRATCH
    cfg = alembic_config(url)
    engine = create_engine(url)
    try:
        command.upgrade(cfg, "0012")
        with engine.begin() as c:
            for i, (name, type_, *_rest) in enumerate(CASES):
                c.execute(
                    text("INSERT INTO contacts (id, name, type, owner_id) VALUES (:i, :n, :t, 1)"),
                    {"i": 100 + i, "n": name, "t": type_},
                )
        command.upgrade(cfg, "0013")
        with engine.connect() as c:
            for i, (name, _type, first, middle, last) in enumerate(CASES):
                row = c.execute(
                    text("SELECT first_name, middle_name, last_name, name FROM contacts WHERE id=:i"),
                    {"i": 100 + i},
                ).one()
                assert tuple(row)[:3] == (first, middle, last), name
                assert row.name == " ".join(name.split()), name
        command.downgrade(cfg, "0012")
        with engine.connect() as c:
            names = {r[0] for r in c.execute(text("SELECT name FROM contacts WHERE id >= 100"))}
        assert names == {" ".join(n.split()) for n, *_ in CASES}
    finally:
        engine.dispose()
        with admin.connect() as c:
            c.execute(text(f"DROP DATABASE IF EXISTS {SCRATCH}"))
        admin.dispose()
