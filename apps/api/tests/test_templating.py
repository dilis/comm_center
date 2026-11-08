import pytest

from app.templating import SUPPORTED, UnknownPlaceholders, render, validate


def test_name_is_the_only_placeholder_for_now():
    assert SUPPORTED == ("name",)


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
        ("Hi {{first_name}} and {{name}}", ["first_name"]),
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
