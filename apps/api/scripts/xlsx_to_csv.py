"""Turn the registration spreadsheet into a CSV that ``scripts.import_contacts_csv`` can import.

    cd apps/api
    uv run python -m scripts.xlsx_to_csv FILE.xlsx OUT.csv

One row per distinct phone number, with the columns
``first_name,middle_name,last_name,phone,email`` (the email is the sheet's ``Customer email``).
The one-cell names are split here, so the result can be read and corrected by hand before it is
imported. Rules, in order:

* a leading title (``Ms``, ``Mr``, ``Dr``...) is dropped;
* the last name is the last word, together with the particles before it (``de Jesus``,
  ``dela Cruz``) and a following suffix (``Jr.``); `` - `` in a double surname is tightened;
* **a middle initial** (a single letter, ``C.`` or ``S``) is the middle name, and *everything
  before it is the first name* (``Zetha Flosy C. Orpilla`` is Zetha Flosy / C. / Orpilla);
* with no initial, the first word is the first name and any words between it and the last name
  are the middle name (these are the names a person should check: they are listed on screen);
* words typed all in capitals or all in lower case are capitalised (``SHIRLEY`` -> ``Shirley``).
"""

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from scripts.import_contacts import ImportProblem, clean_name, plan, read_rows
from scripts.import_contacts_csv import valid_email

COLUMNS = ["first_name", "middle_name", "last_name", "phone", "email"]
TITLES = {"mr", "mrs", "ms", "miss", "dr", "engr", "atty", "sir", "madam", "mam"}
PARTICLES = {"de", "del", "dela", "delos", "la", "los", "san", "santa", "van", "von", "da", "di"}
SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


@dataclass(frozen=True)
class Parts:
    first: str
    middle: str
    last: str
    check: bool = False  # worth a human look: the split was a guess


def _bare(word: str) -> str:
    return word.strip(".").casefold()


def _is_initial(word: str) -> bool:
    return re.fullmatch(r"[^\W\d_]\.?", word) is not None


def _tidy(word: str) -> str:
    """Capitalise a word typed all in capitals or all in lower case (particles stay lower case)."""
    if word.isupper() or (word.islower() and _bare(word) not in PARTICLES):
        return "-".join(part.capitalize() for part in word.split("-"))
    return word


def split_full_name(full: str) -> Parts:
    words = clean_name(re.sub(r"\s*-\s*", "-", full)).split()
    if words and _bare(words[0]) in TITLES and len(words) > 1:
        words = words[1:]
    words = [_tidy(w) for w in words]
    if not words:
        raise ValueError("empty name")
    if len(words) == 1:
        return Parts(words[0], "", "")

    # last name: the last word, its suffix and the particles before it
    end = len(words)
    if _bare(words[-1]) in SUFFIXES and len(words) > 2:
        end -= 1
    start = end - 1
    while start > 1 and _bare(words[start - 1]) in PARTICLES:
        start -= 1
    last = " ".join(words[start:])
    rest = words[:start]

    initial = next((i for i, w in enumerate(rest) if i > 0 and _is_initial(w)), None)
    if initial is not None:
        after = rest[initial + 1 :]
        return Parts(" ".join(rest[:initial]), " ".join([rest[initial], *after]), last, bool(after))
    return Parts(rest[0], " ".join(rest[1:]), last, check=len(rest) > 1)


def _better(kept: str, other: str) -> str:
    """Of two names for one number, the fuller one if it only adds to the other (``Mary Flores``
    and ``Mary T Flores``); otherwise the first."""
    a, b = kept.split(), other.split()
    if len(b) > len(a) and a[0].casefold() == b[0].casefold() and a[-1].casefold() == b[-1].casefold():
        return other
    return kept


def convert(xlsx: Path, out: Path) -> tuple[int, list[str], list[str]]:
    """Write the CSV. Returns (rows written, lines to review, notes about conflicts and skips)."""
    planned = plan(read_rows(xlsx))
    names = {c.phone: c.name for c in planned.contacts if c.named}
    notes = []
    for c in planned.conflicts:
        names[c.phone] = _better(names[c.phone], c.other)
        notes.append(f"{c.phone}: '{c.kept}' and '{c.other}' -> kept '{names[c.phone]}'")
    notes += [f"row {i.line}: skipped, bad number {i.phone!r} ({i.name})" for i in planned.invalid]
    emails = {}
    for c in planned.contacts:
        good = [e for e in c.emails if valid_email(e)]
        emails[c.phone] = good[0] if good else ""
        notes += [f"{c.phone}: ignored invalid email {e!r}" for e in c.emails if e not in good]
        if len(good) > 1:
            notes.append(f"{c.phone}: emails {', '.join(good)} -> kept {good[0]}")
    review = []
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)
        for c in planned.contacts:
            if not c.named:
                writer.writerow([c.phone, "", "", c.phone, emails[c.phone]])
                notes.append(f"{c.phone}: no name; the number is the first name")
                continue
            parts = split_full_name(names[c.phone])
            writer.writerow([parts.first, parts.middle, parts.last, c.phone, emails[c.phone]])
            if parts.check:
                review.append(f"{names[c.phone]!r} -> {parts.first} | {parts.middle} | {parts.last}")
    return len(planned.contacts), review, notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.xlsx_to_csv", description=__doc__.split("\n\n")[0])
    parser.add_argument("xlsx", type=Path)
    parser.add_argument("csv", type=Path)
    args = parser.parse_args(argv)
    try:
        count, review, notes = convert(args.xlsx, args.csv)
    except ImportProblem as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {count} rows to {args.csv}")
    for note in notes:
        print(f"  note: {note}")
    if review:
        print(f"\n{len(review)} names split by guesswork (no middle initial); please check:")
        for line in review:
            print(f"  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
