import pytest

from app.names import split_name


@pytest.mark.parametrize(
    ("full", "parts"),
    [
        ("Ana", ("Ana", None, None)),
        ("Ana Cruz", ("Ana", None, "Cruz")),
        ("Ana Maria Cruz", ("Ana", "Maria", "Cruz")),
        ("  Ana   Maria  Luisa   Cruz ", ("Ana", "Maria Luisa", "Cruz")),
    ],
)
def test_split_name(full, parts):
    assert split_name(full) == parts


def test_a_blank_name_cannot_be_split():
    with pytest.raises(ValueError):
        split_name("   ")
