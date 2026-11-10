"""Split a contact's name into first, middle and last name.

``contacts.name`` becomes a generated column (the parts joined by spaces), so search, sorting and
every place that shows a name keep working. Existing names are split on spaces: the first word is
the first name, the last word the last name and anything between them the middle name. An entity
(a device, a business) and a one-word name keep everything in ``first_name``.

Revision ID: 0013
Revises: 0012
"""
import sqlalchemy as sa

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

# One cleaned copy of the name (trimmed, runs of spaces collapsed), used by the split below.
CLEAN = "REGEXP_REPLACE(TRIM(name), ' +', ' ')"


def upgrade() -> None:
    op.add_column("contacts", sa.Column("first_name", sa.String(length=255), nullable=True))
    op.add_column("contacts", sa.Column("middle_name", sa.String(length=100), nullable=True))
    op.add_column("contacts", sa.Column("last_name", sa.String(length=100), nullable=True))
    op.execute(
        f"""
        UPDATE contacts SET
          first_name = IF(type = 'person', SUBSTRING_INDEX({CLEAN}, ' ', 1), {CLEAN}),
          last_name = IF(type = 'person' AND LOCATE(' ', {CLEAN}) > 0,
                         SUBSTRING_INDEX({CLEAN}, ' ', -1), NULL),
          middle_name = NULL
        """
    )
    # The middle name is the text between the first and last words.
    op.execute(
        f"""
        UPDATE contacts SET middle_name = NULLIF(TRIM(SUBSTRING(
            {CLEAN}, CHAR_LENGTH(first_name) + 1,
            CHAR_LENGTH({CLEAN}) - CHAR_LENGTH(first_name) - CHAR_LENGTH(last_name))), '')
        WHERE type = 'person' AND last_name IS NOT NULL
        """
    )
    op.drop_column("contacts", "name")
    op.alter_column("contacts", "first_name", existing_type=sa.String(length=255), nullable=False)
    op.add_column(
        "contacts",
        sa.Column(
            "name",
            sa.String(length=512),
            sa.Computed("CONCAT_WS(' ', first_name, middle_name, last_name)", persisted=True),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.add_column("contacts", sa.Column("name_plain", sa.String(length=255), nullable=True))
    op.execute("UPDATE contacts SET name_plain = LEFT(name, 255)")
    op.drop_column("contacts", "name")
    op.alter_column(
        "contacts", "name_plain", new_column_name="name", existing_type=sa.String(length=255),
        nullable=False,
    )
    op.drop_column("contacts", "last_name")
    op.drop_column("contacts", "middle_name")
    op.drop_column("contacts", "first_name")
