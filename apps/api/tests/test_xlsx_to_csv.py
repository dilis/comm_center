import pytest

from scripts.xlsx_to_csv import split_full_name


@pytest.mark.parametrize(
    ("full", "first", "middle", "last"),
    [
        ("Randy Marquez", "Randy", "", "Marquez"),
        ("Caleb", "Caleb", "", ""),
        # a middle initial: everything before it is the first name
        ("Zetha Flosy C. Orpilla", "Zetha Flosy", "C.", "Orpilla"),
        ("Fe Regielin S. Catibayan", "Fe Regielin", "S.", "Catibayan"),
        ("Emmanuel I Tamargo", "Emmanuel", "I", "Tamargo"),
        ("Mary Anne T Flores", "Mary Anne", "T", "Flores"),
        ("Kenji A. Gulaga", "Kenji", "A.", "Gulaga"),
        # no initial: first word first, the words between are the middle name
        ("Jhon Paulo Abcede Talato", "Jhon", "Paulo Abcede", "Talato"),
        # particles, suffixes and double surnames belong to the last name
        ("Catherine de Jesus", "Catherine", "", "de Jesus"),
        ("Nestor De Jesus", "Nestor", "", "De Jesus"),
        ("Jose Valenzuela Jr.", "Jose", "", "Valenzuela Jr."),
        ("Syra de Sagon - Navarro", "Syra", "", "de Sagon-Navarro"),
        ("Maria S. dela Cruz", "Maria", "S.", "dela Cruz"),
        # titles go, shouting and lower case are capitalised
        ("Ms Malu Reyes", "Malu", "", "Reyes"),
        ("SHIRLEY MENDOZA", "Shirley", "", "Mendoza"),
        ("Diane manalo", "Diane", "", "Manalo"),
        ("  Ana   Cruz ", "Ana", "", "Cruz"),
    ],
)
def test_split_full_name(full, first, middle, last):
    parts = split_full_name(full)
    assert (parts.first, parts.middle, parts.last) == (first, middle, last)


def test_guessed_splits_are_flagged_and_initials_are_not():
    assert split_full_name("Jhon Paulo Abcede Talato").check
    assert not split_full_name("Zetha Flosy C. Orpilla").check
    assert not split_full_name("Randy Marquez").check
