"""Import contacts (name and phone number) from the ``Details`` sheet of an Excel file.

    cd apps/api
    uv run python -m scripts.import_contacts FILE.xlsx --owner USERNAME --dry-run
    uv run python -m scripts.import_contacts FILE.xlsx --owner USERNAME

Reads the ``Customer name`` and ``Customer phone`` columns (found by header, in any order). Phone
numbers are cleaned up and stored in E.164 (``639171234567``, ``0917 123 4567`` and the like all
become ``+639171234567``). Every contact is a person owned by ``--owner``; a number that is already
in the database is left alone, and the same number on several rows becomes one contact, so running
it again is safe. Everything is written in one transaction: either all of it or none.
"""

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Contact, ContactPhone, User
from app.phones import normalize_e164

SHEET = "Details"
NAME_COLUMN = "Customer name"
PHONE_COLUMN = "Customer phone"
MAX_NAME_LENGTH = 255  # the width of contacts.name


class ImportProblem(Exception):
    """Something to tell the person running the import, without a traceback."""


@dataclass(frozen=True)
class Row:
    line: int  # the row number in the spreadsheet
    name: object
    phone: object


@dataclass
class PlannedContact:
    phone: str
    name: str
    lines: list[int]
    named: bool = True  # False while the name is only the number, used as a stand-in


@dataclass(frozen=True)
class Conflict:
    phone: str
    kept: str
    other: str
    line: int


@dataclass(frozen=True)
class Invalid:
    line: int
    name: str
    phone: object


@dataclass
class Plan:
    contacts: list[PlannedContact] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    invalid: list[Invalid] = field(default_factory=list)

    @property
    def unnamed(self) -> int:
        return sum(not c.named for c in self.contacts)


@dataclass(frozen=True)
class Existing:
    phone: str
    name: str


@dataclass
class Result:
    created: int = 0
    existing: list[Existing] = field(default_factory=list)


def to_e164(raw: object) -> str:
    """A spreadsheet phone value as E.164, or ``ValueError``.

    Handles numbers stored as numbers (no ``+``, possibly a float), national format with spaces or
    dashes, and a leading zero lost by the spreadsheet. Numbers without a country code are read in
    the server's default region (``DEFAULT_PHONE_REGION``, PH unless changed).
    """
    if raw is None or isinstance(raw, bool):
        raise ValueError("no phone number")
    if isinstance(raw, float) and raw.is_integer():
        raw = int(raw)
    text = str(raw).strip()
    if float_text := re.fullmatch(r"(\d+)\.0*", text):  # "639171234567.0"
        text = float_text.group(1)
    cleaned = re.sub(r"[^\d+]", "", text)
    if not cleaned.strip("+"):
        raise ValueError(f"not a phone number: {raw!r}")
    candidates = [cleaned] if cleaned.startswith("+") else [cleaned, "+" + cleaned]
    for candidate in candidates:
        try:
            return normalize_e164(candidate)
        except ValueError:
            continue
    raise ValueError(f"not a valid phone number: {raw!r}")


def clean_name(raw: object) -> str:
    """Trimmed, with runs of whitespace (including non-breaking spaces) collapsed to one space."""
    if raw is None:
        return ""
    return " ".join(str(raw).split())[:MAX_NAME_LENGTH]


def plan(rows: list[Row]) -> Plan:
    """Decide what to import: one contact per valid number, invalid rows set aside."""
    result = Plan()
    by_phone: dict[str, PlannedContact] = {}
    for row in rows:
        name = clean_name(row.name)
        try:
            phone = to_e164(row.phone)
        except ValueError:
            result.invalid.append(Invalid(row.line, name, row.phone))
            continue
        planned = by_phone.get(phone)
        if planned is None:
            planned = by_phone[phone] = PlannedContact(
                phone, name or phone, [row.line], named=bool(name)
            )
            result.contacts.append(planned)
            continue
        planned.lines.append(row.line)
        if not name:
            continue
        if not planned.named:  # the first row had no name; take this one
            planned.name, planned.named = name, True
        elif name.casefold() != planned.name.casefold():
            result.conflicts.append(Conflict(phone, planned.name, name, row.line))
    return result


def read_rows(path: Path) -> list[Row]:
    """The ``Customer name`` and ``Customer phone`` cells of every non-empty row of ``Details``."""
    from openpyxl import load_workbook  # a dev dependency: only this script needs it

    path = Path(path)
    if not path.is_file():
        raise ImportProblem(f"file not found: {path}")
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:  # not an Excel file, corrupt, ...
        raise ImportProblem(f"cannot read {path.name} as an Excel file: {exc}") from exc
    try:
        if SHEET not in workbook.sheetnames:
            raise ImportProblem(
                f"no sheet named {SHEET!r} (found: {', '.join(workbook.sheetnames)})"
            )
        rows = workbook[SHEET].iter_rows(values_only=True)
        headers = [str(h).strip() if h is not None else "" for h in next(rows, ())]
        lookup = {h.casefold(): i for i, h in enumerate(headers) if h}
        columns = []
        for wanted in (NAME_COLUMN, PHONE_COLUMN):
            if wanted.casefold() not in lookup:
                found = ", ".join(h for h in headers if h)
                raise ImportProblem(
                    f"column {wanted!r} not found in the {SHEET} sheet (found: {found})"
                )
            columns.append(lookup[wanted.casefold()])
        name_at, phone_at = columns
        result = []
        for line, cells in enumerate(rows, start=2):
            if all(c is None or str(c).strip() == "" for c in cells):
                continue
            padded = list(cells) + [None] * (max(columns) + 1 - len(cells))
            result.append(Row(line, padded[name_at], padded[phone_at]))
        return result
    finally:
        workbook.close()


def resolve_owner(db: Session, username: str) -> int:
    """The id of the human user who will own the imported contacts."""
    found = db.execute(
        select(User.id, User.is_active, User.is_system).where(User.username == username)
    ).one_or_none()
    if found is None or found.is_system:
        raise ImportProblem(f"no user named {username!r} (system agents cannot own imports)")
    if not found.is_active:
        raise ImportProblem(f"user {username!r} is inactive")
    return found.id


def apply(db: Session, planned: Plan, owner_id: int) -> Result:
    """Add the contacts that are not in the database yet. The caller commits (or rolls back)."""
    result = Result()
    existing: dict[str, str] = {}
    numbers = [c.phone for c in planned.contacts]
    for start in range(0, len(numbers), 500):
        rows = db.execute(
            select(ContactPhone.phone_e164, Contact.name)
            .join(Contact, Contact.id == ContactPhone.contact_id)
            .where(ContactPhone.phone_e164.in_(numbers[start : start + 500]))
        )
        existing.update(dict(rows.all()))
    for item in planned.contacts:
        if item.phone in existing:
            result.existing.append(Existing(item.phone, existing[item.phone]))
            continue
        contact = Contact(name=item.name, type="person", owner_id=owner_id)
        db.add(contact)
        db.flush()
        db.add(ContactPhone(contact_id=contact.id, phone_e164=item.phone, is_primary=True))
        result.created += 1
    db.flush()
    return result


def report(rows: list[Row], planned: Plan, result: Result, dry_run: bool, verbose: bool) -> str:
    lines = []
    if dry_run:
        lines.append("DRY RUN: nothing was saved.")
    created = "Contacts that would be created" if dry_run else "Contacts created"
    table = [
        ("Rows read", str(len(rows))),
        ("Distinct phone numbers", str(len(planned.contacts))),
        (created, str(result.created)),
        ("Already in the database", f"{len(result.existing)} (left unchanged)"),
        ("Rows with a bad number", str(len(planned.invalid))),
        ("Numbers under 2+ names", f"{len(planned.conflicts)} (the first name was kept)"),
        ("Contacts without a name", f"{planned.unnamed} (the number was used as the name)"),
    ]
    lines += [f"{label + ':':<33}{value}" for label, value in table]
    if planned.invalid:
        lines.append("\nRows skipped because the phone number is unusable:")
        lines += [f"  row {i.line}: {i.name or '(no name)'} - {i.phone!r}" for i in planned.invalid]
    if planned.conflicts:
        lines.append("\nNumbers that appear under different names (first name kept):")
        lines += [
            f"  row {c.line}: {c.phone} is {c.kept!r}, also listed as {c.other!r}"
            for c in planned.conflicts
        ]
    if verbose and result.existing:
        lines.append("\nAlready in the database:")
        lines += [f"  {e.phone} ({e.name})" for e in result.existing]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scripts.import_contacts", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("file", type=Path, help="the .xlsx file")
    parser.add_argument(
        "--owner", required=True, help="username of the user who will own the contacts"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="do everything but save, and show the result"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="also list numbers that already exist"
    )
    args = parser.parse_args(argv)

    from sqlalchemy.exc import IntegrityError

    from app.db import SessionLocal

    try:
        rows = read_rows(args.file)
        planned = plan(rows)
        with SessionLocal() as db:
            try:
                result = apply(db, planned, resolve_owner(db, args.owner))
                db.rollback() if args.dry_run else db.commit()
            except IntegrityError as exc:
                db.rollback()
                raise ImportProblem(
                    f"the database refused a row (was another process adding contacts?): {exc.orig}"
                ) from exc
    except ImportProblem as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(report(rows, planned, result, args.dry_run, args.verbose))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
