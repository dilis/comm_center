"""Import contacts from a CSV file.

    cd apps/api
    uv run python -m scripts.import_contacts_csv FILE.csv --owner USERNAME --dry-run
    uv run python -m scripts.import_contacts_csv FILE.csv --owner USERNAME

The CSV (UTF-8, a header row, columns in any order, letter case ignored):

    first_name,middle_name,last_name,phone,email
    Zetha Flosy,C.,Orpilla,0947 711 4810,zetha@example.com

``first_name`` and ``phone`` are required; ``middle_name``, ``last_name`` and ``email`` may be
empty or the column absent (an invalid email is dropped and reported, the contact is still made). ``scripts.xlsx_to_csv`` makes such a file from the registration spreadsheet. Phone
numbers are stored in E.164 (a number without a country code is read as Philippine). Every contact
is a person owned by ``--owner``. A number already in the database is left alone, the same number
on several rows becomes one contact (the first row wins), and everything is saved in one
transaction or not at all, so running it again is safe. A row with a bad number or no first name
is skipped and listed; with ``--strict`` any such row stops the import instead.
"""

import argparse
import csv
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Contact, ContactPhone
from scripts.import_contacts import ImportProblem, clean_name, resolve_owner, to_e164

REQUIRED = ("first_name", "phone")
OPTIONAL = ("middle_name", "last_name", "email")
LIMITS = {"first_name": 255, "middle_name": 100, "last_name": 100}
_EMAIL = TypeAdapter(EmailStr)


def valid_email(value: str) -> bool:
    try:
        _EMAIL.validate_python(value)
    except ValidationError:
        return False
    return len(value) <= 255


@dataclass(frozen=True)
class CsvRow:
    line: int  # the line in the file
    first_name: str
    middle_name: str
    last_name: str
    phone: str
    email: str = ""


@dataclass(frozen=True)
class Skipped:
    line: int
    reason: str


@dataclass
class Plan:
    contacts: list[tuple[CsvRow, str]] = field(default_factory=list)  # (row, E.164 number)
    skipped: list[Skipped] = field(default_factory=list)
    duplicates: list[Skipped] = field(default_factory=list)
    bad_emails: list[Skipped] = field(default_factory=list)  # imported without the email


@dataclass
class Result:
    created: int = 0
    existing: list[str] = field(default_factory=list)


def read_rows(path: Path) -> list[CsvRow]:
    path = Path(path)
    if not path.is_file():
        raise ImportProblem(f"file not found: {path}")
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.reader(handle)
            header = next(reader, None)
            if header is None:
                raise ImportProblem("the file is empty")
            index = {h.strip().casefold(): i for i, h in enumerate(header) if h.strip()}
            for wanted in REQUIRED:
                if wanted not in index:
                    raise ImportProblem(
                        f"column {wanted!r} not found (found: {', '.join(h for h in header if h)})"
                    )
            rows = []
            for line, cells in enumerate(reader, start=2):
                if not any(c.strip() for c in cells):
                    continue

                def cell(name: str, cells: list[str] = cells) -> str:
                    at = index.get(name)
                    return clean_name(cells[at]) if at is not None and at < len(cells) else ""

                rows.append(
                    CsvRow(line, cell("first_name"), cell("middle_name"), cell("last_name"), cell("phone"), cell("email").casefold())
                )
            return rows
    except UnicodeDecodeError as exc:
        raise ImportProblem(f"{path.name} is not UTF-8 text: {exc}") from exc
    except csv.Error as exc:
        raise ImportProblem(f"cannot read {path.name} as CSV: {exc}") from exc


def plan(rows: list[CsvRow]) -> Plan:
    result = Plan()
    first_seen: dict[str, int] = {}
    for row in rows:
        if not row.first_name:
            result.skipped.append(Skipped(row.line, "no first_name"))
            continue
        too_long = [f for f, n in LIMITS.items() if len(getattr(row, f)) > n]
        if too_long:
            result.skipped.append(Skipped(row.line, f"{', '.join(too_long)} too long"))
            continue
        try:
            phone = to_e164(row.phone)
        except ValueError as exc:
            result.skipped.append(Skipped(row.line, str(exc)))
            continue
        if phone in first_seen:
            result.duplicates.append(
                Skipped(row.line, f"{phone} already on line {first_seen[phone]}")
            )
            continue
        first_seen[phone] = row.line
        if row.email and not valid_email(row.email):
            result.bad_emails.append(Skipped(row.line, f"invalid email {row.email!r}, left out"))
            row = replace(row, email="")
        result.contacts.append((row, phone))
    return result


def apply(db: Session, planned: Plan, owner_id: int) -> Result:
    """Add the contacts whose number is not in the database yet. The caller commits."""
    result = Result()
    numbers = [phone for _, phone in planned.contacts]
    existing: set[str] = set()
    for start in range(0, len(numbers), 500):
        existing.update(
            db.scalars(
                select(ContactPhone.phone_e164).where(
                    ContactPhone.phone_e164.in_(numbers[start : start + 500])
                )
            )
        )
    for row, phone in planned.contacts:
        if phone in existing:
            result.existing.append(phone)
            continue
        contact = Contact(
            first_name=row.first_name,
            middle_name=row.middle_name or None,
            last_name=row.last_name or None,
            email=row.email or None,
            type="person",
            owner_id=owner_id,
        )
        db.add(contact)
        db.flush()
        db.add(ContactPhone(contact_id=contact.id, phone_e164=phone, is_primary=True))
        result.created += 1
    db.flush()
    return result


def report(rows: list[CsvRow], planned: Plan, result: Result, dry_run: bool, verbose: bool) -> str:
    lines = ["DRY RUN: nothing was saved."] if dry_run else []
    created = "Contacts that would be created" if dry_run else "Contacts created"
    for label, value in [
        ("Rows read", len(rows)),
        ("Distinct phone numbers", len(planned.contacts)),
        (created, result.created),
        ("Already in the database", f"{len(result.existing)} (left unchanged)"),
        ("Rows skipped", len(planned.skipped)),
        ("Repeated numbers", f"{len(planned.duplicates)} (the first row was kept)"),
        ("Invalid emails", f"{len(planned.bad_emails)} (contact made without it)"),
    ]:
        lines.append(f"{label + ':':<32}{value}")
    if planned.skipped:
        lines.append("\nSkipped rows:")
        lines += [f"  line {s.line}: {s.reason}" for s in planned.skipped]
    if planned.bad_emails:
        lines.append("\nInvalid emails:")
        lines += [f"  line {b.line}: {b.reason}" for b in planned.bad_emails]
    if planned.duplicates:
        lines.append("\nRepeated numbers:")
        lines += [f"  line {d.line}: {d.reason}" for d in planned.duplicates]
    if verbose and result.existing:
        lines.append("\nAlready in the database:")
        lines += [f"  {phone}" for phone in result.existing]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scripts.import_contacts_csv", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("file", type=Path, help="the .csv file")
    parser.add_argument("--owner", required=True, help="username of the user who will own the contacts")
    parser.add_argument("--dry-run", action="store_true", help="do everything but save")
    parser.add_argument("--verbose", action="store_true", help="also list numbers that already exist")
    parser.add_argument("--strict", action="store_true", help="stop if any row would be skipped")
    args = parser.parse_args(argv)

    from sqlalchemy.exc import IntegrityError

    from app.db import SessionLocal

    try:
        rows = read_rows(args.file)
        planned = plan(rows)
        if args.strict and planned.skipped:
            raise ImportProblem(
                "--strict: "
                + "; ".join(f"line {s.line}: {s.reason}" for s in planned.skipped)
            )
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
