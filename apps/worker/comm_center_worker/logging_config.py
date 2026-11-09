"""One log format for the worker: ``2026-11-09 08:00:00 INFO comm_center_worker: message``.

It writes to stderr, so a container runtime or systemd collects it. The level comes from the
``LOG_LEVEL`` setting.
"""

import logging

LEVELS = {n: getattr(logging, n) for n in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")}
FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(level: str) -> None:
    resolved = LEVELS.get(level.strip().upper())
    if resolved is None:
        raise ValueError(
            f"LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR or CRITICAL, not {level!r}"
        )
    root = logging.getLogger()
    root.setLevel(resolved)
    if not any(getattr(h, "_comm_center", False) for h in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(FORMAT))
        handler._comm_center = True  # type: ignore[attr-defined]  # so a second call adds no twin
        root.addHandler(handler)
