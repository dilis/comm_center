"""Placeholders in message text: ``Hello {{name}}`` becomes ``Hello Ana Cruz``, per recipient.

Rendering happens when the message is created, so the stored text is exactly what is sent and the
message log stays immutable. Only ``name`` exists for now; add more to ``SUPPORTED`` and pass their
values to ``render``.
"""

import re
from collections.abc import Mapping

SUPPORTED = ("name",)
_PLACEHOLDER = re.compile(r"\{\{\s*([^{}]*?)\s*\}\}")


class UnknownPlaceholders(ValueError):
    def __init__(self, names: list[str]) -> None:
        self.names = names
        listed = ", ".join("{{" + n + "}}" for n in names)
        supported = ", ".join("{{" + n + "}}" for n in SUPPORTED)
        super().__init__(f"unknown placeholder {listed}; supported: {supported}")


def validate(template: str) -> None:
    """Raise ``UnknownPlaceholders`` if the text uses a placeholder that does not exist."""
    unknown = [n for n in dict.fromkeys(_PLACEHOLDER.findall(template)) if n not in SUPPORTED]
    if unknown:
        raise UnknownPlaceholders(unknown)


def render(template: str, values: Mapping[str, str]) -> str:
    """Fill in the placeholders. Values are inserted literally (never re-expanded)."""
    return _PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), template)
