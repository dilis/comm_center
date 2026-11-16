"""The id given to the Android gateway for a message: ``cc-<id>``, with ``-<n>`` on the n-th retry."""

import pytest

from app.dispatch import gateway_message_id, parse_gateway_message_id


def test_the_first_send_has_a_clean_id():
    assert gateway_message_id(175, 0) == "cc-175"
    assert gateway_message_id(175) == "cc-175"


def test_a_retry_appends_its_number():
    assert gateway_message_id(175, 1) == "cc-175-1"
    assert gateway_message_id(175, 12) == "cc-175-12"


@pytest.mark.parametrize(
    ("value", "parsed"),
    [("cc-175", (175, 0)), ("cc-175-1", (175, 1)), ("cc-7-12", (7, 12))],
)
def test_ids_are_read_back(value, parsed):
    assert parse_gateway_message_id(value) == parsed


@pytest.mark.parametrize(
    "value",
    ["", None, 5, "abc", "cc-", "cc-x", "cc--1", "cc-1-", "cc-1-x", "cc-1-0", "cc-1-01", "cc-1-2-3", "cc-01"],
)
def test_anything_else_is_not_ours(value):
    assert parse_gateway_message_id(value) is None
