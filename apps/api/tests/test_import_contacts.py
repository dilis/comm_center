"""The spreadsheet importer's pure parts: phone and name clean-up, reading the sheet, planning."""

import pytest
from openpyxl import Workbook

from scripts.import_contacts import ImportProblem, Row, clean_name, plan, read_rows, to_e164


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (639816259914, "+639816259914"),  # a numeric cell: no "+", as the spreadsheet stores it
        (639816259914.0, "+639816259914"),  # the same number as a float
        ("639816259914", "+639816259914"),
        ("639816259914.0", "+639816259914"),  # a float that was turned into text
        ("0917 123 4567", "+639171234567"),  # national format
        ("0917-123-4567", "+639171234567"),
        ("+63 917 123 4567", "+639171234567"),
        ("(0917) 123 4567", "+639171234567"),
        (9171234567, "+639171234567"),  # the leading zero was lost by the spreadsheet
        ("  639171234567  ", "+639171234567"),
        ("+14155552671", "+14155552671"),  # a number from another country is kept as it is
    ],
)
def test_phone_numbers_are_normalized_to_e164(raw, expected):
    assert to_e164(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "n/a", "12345", 123, "+", True])
def test_unusable_phone_values_are_rejected(raw):
    with pytest.raises(ValueError):
        to_e164(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Ana Cruz", "Ana Cruz"),
        ("  Ana Cruz ", "Ana Cruz"),
        ("Ana    Cruz", "Ana Cruz"),
        ("Ana Cruz\t", "Ana Cruz"),  # a non-breaking space pasted from a web page
        ("Ana\nCruz", "Ana Cruz"),
        (None, ""),
        ("   ", ""),
        (12345, "12345"),
        ("x" * 300, "x" * 255),  # the column holds 255 characters
    ],
)
def test_names_are_tidied(raw, expected):
    assert clean_name(raw) == expected


def row(line, name, phone):
    return Row(line=line, name=name, phone=phone)


def test_one_contact_per_number_first_name_wins():
    result = plan(
        [
            row(2, "Ana Cruz", 639171234567),
            row(3, "Ben Lim", 639181234567),
            row(4, "Ana Cruz", "0917 123 4567"),
        ]
    )
    assert [(c.phone, c.name, c.lines) for c in result.contacts] == [
        ("+639171234567", "Ana Cruz", [2, 4]),
        ("+639181234567", "Ben Lim", [3]),
    ]
    assert result.conflicts == []


def test_same_name_in_another_case_or_spacing_is_not_a_conflict():
    result = plan([row(2, "Ana Cruz", 639171234567), row(3, "  ANA  cruz ", 639171234567)])
    assert len(result.contacts) == 1 and result.conflicts == []


def test_a_number_under_two_different_names_is_reported_and_keeps_the_first():
    result = plan([row(2, "Ana Cruz", 639171234567), row(3, "Someone Else", 639171234567)])
    assert result.contacts[0].name == "Ana Cruz"
    assert [(c.phone, c.kept, c.other, c.line) for c in result.conflicts] == [
        ("+639171234567", "Ana Cruz", "Someone Else", 3)
    ]


def test_invalid_numbers_are_reported_with_their_row_and_not_imported():
    result = plan([row(2, "Ana", "12345"), row(3, "Ben", None), row(4, "Cy", 639171234567)])
    assert [c.name for c in result.contacts] == ["Cy"]
    assert [(i.line, i.name) for i in result.invalid] == [(2, "Ana"), (3, "Ben")]


def test_a_missing_name_falls_back_to_the_number():
    result = plan([row(2, None, 639171234567), row(3, "   ", 639181234567)])
    assert [c.name for c in result.contacts] == ["+639171234567", "+639181234567"]
    assert result.unnamed == 2


def test_a_name_gets_filled_in_by_a_later_row_if_the_first_had_none():
    result = plan([row(2, None, 639171234567), row(3, "Ana Cruz", 639171234567)])
    assert result.contacts[0].name == "Ana Cruz"
    assert result.unnamed == 0 and result.conflicts == []


def sheet_file(
    tmp_path, rows, headers=("Date", "Customer name", "Customer phone", "Status"), sheet="Details"
):
    wb = Workbook()
    wb.active.title = "Summary"
    wb.active.append(["Customer name", "Customer phone"])  # decoy: only Details counts
    wb.active.append(["Decoy", 639990000000])
    ws = wb.create_sheet(sheet)
    ws.append(list(headers))
    for r in rows:
        ws.append(r)
    path = tmp_path / "book.xlsx"
    wb.save(path)
    return path


def test_rows_are_read_from_the_details_sheet_by_header_name(tmp_path):
    path = sheet_file(
        tmp_path,
        [
            ["2026-11-01", "Ana Cruz", 639171234567, "Completed"],
            ["2026-11-02", "Ben", 639181234567, "Pending"],
        ],
    )
    assert read_rows(path) == [Row(2, "Ana Cruz", 639171234567), Row(3, "Ben", 639181234567)]


def test_columns_may_be_in_any_order_and_in_any_case(tmp_path):
    path = sheet_file(
        tmp_path,
        [[639171234567, "Ana", "x"]],
        headers=("customer PHONE ", " Customer Name", "Other"),
    )
    assert read_rows(path) == [Row(2, "Ana", 639171234567)]


def test_completely_empty_rows_are_skipped_but_row_numbers_stay_true(tmp_path):
    path = sheet_file(
        tmp_path,
        [
            ["d", "Ana", 639171234567, "s"],
            [None, None, None, None],
            ["d", "Ben", 639181234567, "s"],
        ],
    )
    assert [r.line for r in read_rows(path)] == [2, 4]


def test_a_row_with_only_one_of_the_two_values_is_kept_so_it_gets_reported(tmp_path):
    path = sheet_file(tmp_path, [["d", "Ana", None, "s"], ["d", None, 639181234567, "s"]])
    assert [(r.name, r.phone) for r in read_rows(path)] == [("Ana", None), (None, 639181234567)]


def test_a_missing_details_sheet_is_explained(tmp_path):
    path = sheet_file(tmp_path, [], sheet="Other")
    with pytest.raises(ImportProblem, match="Details.*Summary, Other"):
        read_rows(path)


def test_a_missing_column_is_explained(tmp_path):
    path = sheet_file(tmp_path, [], headers=("Date", "Customer name"))
    with pytest.raises(ImportProblem, match="Customer phone.*Date, Customer name"):
        read_rows(path)


def test_a_missing_file_is_explained(tmp_path):
    with pytest.raises(ImportProblem, match="not found"):
        read_rows(tmp_path / "nope.xlsx")


def test_the_report_lines_up_and_says_when_nothing_was_saved():
    from scripts.import_contacts import Result, report

    rows = [row(2, "Ana", 639171234567), row(3, "Ben", "12345")]
    dry = report(rows, plan(rows), Result(created=1), dry_run=True, verbose=False)
    real = report(rows, plan(rows), Result(created=1), dry_run=False, verbose=False)
    assert dry.startswith("DRY RUN: nothing was saved.")
    assert "Contacts that would be created:" in dry and "DRY RUN" not in real
    values = [line[33:] for line in real.splitlines()[:7]]
    assert values[:5] == [
        "2",
        "1",
        "1",
        "0 (left unchanged)",
        "1",
    ]  # every value starts in one column
    assert "row 3: Ben - '12345'" in real
