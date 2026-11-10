# Importing contacts from a spreadsheet

`apps/api/scripts/import_contacts.py` reads the **`Details`** sheet of an Excel file and creates one
contact (a person, with one primary phone number) per distinct phone number.

| It reads | Column header (any column position, any letter case) |
|---|---|
| Name | `Customer name` |
| Phone number | `Customer phone` |

Nothing else in the sheet is imported (not the email, the order status or the other columns).

## What it does with the data

- **Phone numbers** are cleaned and stored in international format (E.164). Numbers stored as plain
  numbers (`639171234567`), with spaces or dashes (`0917 123 4567`), with a `+`, or with the leading
  zero lost (`9171234567`) all become `+639171234567`. Numbers without a country code are read as
  Philippine numbers (`DEFAULT_PHONE_REGION`). A value that is not a phone number is skipped and
  listed in the report.
- **Names** are trimmed and repeated spaces are collapsed. They are otherwise kept exactly as typed.
  A missing name falls back to the number, the same way contacts made from received messages do.
- **The same number on several rows** (for example someone who registered twice) becomes one contact.
  If those rows give different names, the first name is kept and the report lists the others.
- **A number already in the database** is left alone: the existing contact is not changed and no
  duplicate is made. So running the script again, or on an updated copy of the file, only adds what
  is new.
- **Owner:** every contact is owned by the user you name with `--owner`. That user sees them under
  the `read_own` permission; anyone with `contacts:read_all` sees them either way.
- **All or nothing:** the whole import is one database transaction. If anything fails, nothing is
  saved.

## How to run it

You need the database running (`docker compose up -d --wait db`, or `pnpm docker:up`) and an
existing user to be the owner (the admin you created with `create-admin`, for example). Run these
from the repository root.

```sh
cd apps/api
uv sync          # once: installs the Excel reader (openpyxl)
```

1. **Dry run first.** It does everything except save, and prints what would happen:
   ```sh
   uv run python -m scripts.import_contacts "../../Counseling the Heart Registration Count.xlsx" --owner admin --dry-run
   ```
2. **Read the report.** Check the rows it skipped and the numbers listed under two names.
3. **Import for real** (the same command without `--dry-run`):
   ```sh
   uv run python -m scripts.import_contacts "../../Counseling the Heart Registration Count.xlsx" --owner admin
   ```
4. Open the Contacts page: the new contacts are there, sorted newest first by default.

The same thing through pnpm (the quotes matter because the file name has spaces; the path is
relative to `apps/api`):
```sh
pnpm --filter @comm-center/api import-contacts -- "../../Counseling the Heart Registration Count.xlsx" --owner admin --dry-run
```

Options: `--dry-run` (save nothing), `--verbose` (also list the numbers that already existed).
Replace `admin` with the username that should own the contacts. The database it uses is the one in
`DATABASE_URL` (by default the compose database on port 3307).

## Reading the report

```
Rows read:                 92      rows with data in the sheet
Distinct phone numbers:    74      what becomes contacts, at most
Contacts created:          ...     new contacts (with --dry-run: "that would be created")
Already in the database:   ...     skipped, left unchanged
Rows with a bad number:    0       listed below with their spreadsheet row number
Numbers under 2+ names:    1       listed below; the first name was kept
Contacts without a name:   0       the number was used as the name
```

A quick look at the file (not by running the script) found 92 rows, 74 distinct numbers, all of them
valid, and one number listed under two different names, so a first run on an empty contact list
should create 74 contacts.

## If it says...

| Message | Meaning |
|---|---|
| `no sheet named 'Details'` | The file has no `Details` sheet; the message lists the sheets it found. |
| `column 'Customer phone' not found` | A header is missing or renamed; the message lists the headers it found. |
| `no user named 'x'` | `--owner` must be the username of an existing, active person (not a system agent). |
| `file not found` | Check the path. It is relative to where you run the command (`apps/api`). |
| `the database refused a row` | Another process added the same number while it ran. Nothing was saved; run it again. |

## Undoing an import

Soft-delete the contacts from the Contacts page, or by owner in the database
(`UPDATE contacts SET deleted_at = NOW() WHERE owner_id = <id> AND created_at >= '<start of the run>'`;
also soft-delete their `contact_phone` rows, which frees the numbers). There is no automatic undo,
which is why the dry run comes first.

## About the spreadsheet

It holds personal data, so `*.xlsx` is in `.gitignore`: it cannot be committed by accident.

## Importing from a CSV file (names split into first, middle and last)

The Excel importer above keeps the whole name in one cell and splits it with a simple rule (first
word, last word, the rest in between). For names that need care, go through a CSV you can read and
correct before importing.

1. **Make the CSV from the spreadsheet** (from `apps/api`):
   ```sh
   uv run python -m scripts.xlsx_to_csv "../../Counseling the Heart Registration Count.xlsx" ../../contacts_import.csv
   ```
   It writes `first_name,middle_name,last_name,phone,email` (the email is the sheet's `Customer email`; if one number has several emails the first is kept and the rest are noted), one row per distinct number, and prints the
   names it had to guess. The rules: a **middle initial** (`C.`, `S`) is the middle name and
   *everything before it is the first name* (`Zetha Flosy C. Orpilla` is Zetha Flosy / C. /
   Orpilla); particles (`de`, `dela`) and suffixes (`Jr.`) stay with the last name; a leading `Ms` or
   `Mr` is dropped; ALL CAPS or all lower case words are capitalised; with no initial the first word
   is the first name and the words between it and the last name are the middle name (those are the
   rows it lists for you to check). When one number has two spellings, the fuller one is kept.
2. **Open the CSV and correct it** (a spreadsheet program works; save as UTF-8 CSV).
3. **Dry run, then import:**
   ```sh
   uv run python -m scripts.import_contacts_csv ../../contacts_import.csv --owner admin --dry-run
   uv run python -m scripts.import_contacts_csv ../../contacts_import.csv --owner admin
   ```
   Options: `--verbose` (list numbers that already exist), `--strict` (stop instead of skipping bad
   rows). `first_name` and `phone` are required; `middle_name`, `last_name` and `email` may be empty or
   absent (an invalid email is left out and reported); column order and header case do not matter. Phone handling, ownership, "number already in
   the database is left alone" and all-or-nothing are the same as above.

Contacts already imported keep their names: the importer never edits an existing contact. To redo
them, soft-delete those contacts first (see "Undoing an import").

`*.csv` is in `.gitignore`, like `*.xlsx`.
