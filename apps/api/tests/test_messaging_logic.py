import pytest

from app.messaging import derive_direction


@pytest.mark.parametrize(
    ("is_system", "agent_direction", "expected"),
    [
        (False, None, "outbound"),  # a human owner always sent it
        (True, "inbound", "inbound"),  # a device agent received it
        (True, "outbound", "outbound"),  # the notification agent sent it
    ],
)
def test_direction_is_derived_from_the_owner(is_system, agent_direction, expected):
    assert derive_direction(is_system, agent_direction) == expected


def test_inconsistent_owner_is_rejected():
    with pytest.raises(ValueError):
        derive_direction(True, None)
