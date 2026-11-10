import pytest

from app.templating import SUPPORTED, UnknownPlaceholders, render, validate


def test_the_supported_placeholders():
    assert SUPPORTED == ("name", "first_name", "last_name")


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("Hello {{name}}!", "Hello Ana Cruz!"),
        ("Hello {{ name }}!", "Hello Ana Cruz!"),  # spaces inside the braces are fine
        ("Hello {{  name\t}}!", "Hello Ana Cruz!"),
        ("{{name}}, {{name}}", "Ana Cruz, Ana Cruz"),  # every occurrence
        ("{{name}}", "Ana Cruz"),
        ("No placeholders here", "No placeholders here"),
        ("", ""),
        ("Single {name} braces are text", "Single {name} braces are text"),
        ("Unclosed {{name and {{ also", "Unclosed {{name and {{ also"),
        ("Line one\n{{name}}\nLine three", "Line one\nAna Cruz\nLine three"),
    ],
)
def test_names_are_filled_in(template, expected):
    assert render(template, {"name": "Ana Cruz"}) == expected


@pytest.mark.parametrize("name", ["A\\1 B", "$0 money", "back\\slash", "{{name}}", "Zoë Ñandú 李"])
def test_the_name_is_inserted_literally(name):
    # not read as a regex group reference, and not expanded again if it looks like a placeholder
    assert render("Hi {{name}}.", {"name": name}) == f"Hi {name}."


@pytest.mark.parametrize("template", ["Hi {{name}}", "{{ name }} {{name}}", "plain", "", "{name}"])
def test_valid_templates_pass(template):
    validate(template)


@pytest.mark.parametrize(
    ("template", "bad"),
    [
        ("Hi {{nam}}", ["nam"]),
        ("Hi {{Name}}", ["Name"]),  # placeholders are lowercase
        ("Hi {{nickname}} and {{name}}", ["nickname"]),
        ("{{ }}", [""]),
        ("{{}}", [""]),
        ("{{foo}} {{bar}} {{foo}}", ["foo", "bar"]),  # each once, in order of appearance
    ],
)
def test_unknown_placeholders_are_rejected_not_sent_as_text(template, bad):
    with pytest.raises(UnknownPlaceholders) as caught:
        validate(template)
    assert caught.value.names == bad
    assert "name" in str(caught.value)  # says what is supported


def test_first_and_last_name_fill_in_and_a_missing_last_name_is_empty():
    values = {"name": "Ana Maria Cruz", "first_name": "Ana", "last_name": "Cruz"}
    assert render("{{first_name}} / {{last_name}} / {{name}}", values) == "Ana / Cruz / Ana Maria Cruz"
    assert render("Hi {{first_name}}{{last_name}}.", {"first_name": "Ana", "last_name": ""}) == "Hi Ana."
