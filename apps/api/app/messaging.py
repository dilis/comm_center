"""Message direction is derived from the owner, never stored (SPECS.md 4.2)."""

from typing import Literal

from sqlalchemy import Select, select

from app.models import User

Direction = Literal["inbound", "outbound"]


def derive_direction(is_system: bool, agent_direction: str | None) -> Direction:
    """A human owner sent it; a system agent follows its ``agent_direction``."""
    if not is_system:
        return "outbound"
    if agent_direction not in ("inbound", "outbound"):
        raise ValueError("a system agent must have an agent_direction")
    return agent_direction


def inbound_agent_ids() -> Select:
    """Owners whose messages are inbound. System agents are never soft-deleted, so this is exact."""
    return select(User.id).where(User.is_system.is_(True), User.agent_direction == "inbound")
