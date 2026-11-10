import pytest

from scripts.import_contacts import ImportProblem
from scripts.import_contacts_csv import plan, read_rows


def write(tmp_path, text, encoding="utf-8"):
    path = tmp_path / "in.csv"
    path.write_text(text, encoding=encoding)
    return path


def test_reads_columns_by_header_in_any_order_and_case(tmp_path):
    rows = read_rows(write(tmp_path, "Phone,Last_Name,FIRST_NAME\n0917 123 4567,Cruz,Ana\n"))
    assert [(r.first_name, r.middle_name, r.last_name, r.phone, r.line) for r in rows] == [
        ("Ana", "", "Cruz", "0917 123 4567", 2)
    ]


def test_optional_columns_may_be_missing_and_blank_lines_are_ignored(tmp_path):
    rows = read_rows(write(tmp_path, "first_name,phone\nAna,0917 123 4567\n,\n\nBen,0918 123 4567\n"))
    assert [r.first_name for r in rows] == ["Ana", "Ben"] and rows[1].line == 5


def test_an_excel_byte_order_mark_is_ignored(tmp_path):
    rows = read_rows(write(tmp_path, "first_name,phone\nAna,09171234567\n", "utf-8-sig"))
    assert rows[0].first_name == "Ana"


def test_values_with_commas_and_quotes_and_accents(tmp_path):
    rows = read_rows(write(tmp_path, 'first_name,last_name,phone\n"Ana, Jr.",Bañaga,09171234567\n'))
    assert (rows[0].first_name, rows[0].last_name) == ("Ana, Jr.", "Bañaga")


@pytest.mark.parametrize("header", ["first_name,last_name", "name,phone", ""])
def test_missing_required_columns_or_empty_file(tmp_path, header):
    with pytest.raises(ImportProblem):
        read_rows(write(tmp_path, header))


def test_missing_file(tmp_path):
    with pytest.raises(ImportProblem, match="file not found"):
        read_rows(tmp_path / "nope.csv")


def test_plan_normalises_numbers_and_sets_bad_rows_aside(tmp_path):
    rows = read_rows(
        write(
            tmp_path,
            "first_name,last_name,phone\n"
            "Ana,Cruz,0917 123 4567\n"
            "Ana again,Cruz,+63 917 123 4567\n"  # same number
            "Ben,Lim,hello\n"
            ",Nobody,09181234567\n"
            "Cy,Tan,09191234567\n",
        )
    )
    planned = plan(rows)
    assert [(r.first_name, p) for r, p in planned.contacts] == [
        ("Ana", "+639171234567"),
        ("Cy", "+639191234567"),
    ]
    assert [s.line for s in planned.skipped] == [4, 5]
    assert [d.line for d in planned.duplicates] == [3]


def test_email_is_optional_lower_cased_and_an_invalid_one_is_left_out(tmp_path):
    rows = read_rows(
        write(
            tmp_path,
            "first_name,phone,email\nAna,09171234567, Ana@Example.COM \nBen,09181234567,not-an-email\nCy,09191234567,\n",
        )
    )
    planned = plan(rows)
    assert [r.email for r, _ in planned.contacts] == ["ana@example.com", "", ""]
    assert [b.line for b in planned.bad_emails] == [3]
    assert planned.skipped == []
