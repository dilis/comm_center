import pytest

from app.phones import normalize_e164


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("+639171234567", "+639171234567"),
        ("+63 917 123 4567", "+639171234567"),
        ("0917-123-4567", "+639171234567"),  # national format, default region PH
        ("(917) 123 4567", "+639171234567"),
    ],
)
def test_normalizes_to_e164(raw, expected):
    assert normalize_e164(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "12", "+1", "+63917", "00000000000"])
def test_rejects_invalid_numbers(raw):
    with pytest.raises(ValueError):
        normalize_e164(raw)


def test_explicit_region_overrides_default():
    assert normalize_e164("(415) 555-2671", region="US") == "+14155552671"
