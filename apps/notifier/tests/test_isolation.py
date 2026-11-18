"""The notifier shares only the outbox tables with the API (SPECS.md, Phase 9): none of the API's
code, and no ORM."""

import subprocess
import sys
from pathlib import Path

NOTIFIER_DIR = Path(__file__).resolve().parents[1]


def test_importing_the_notifier_loads_neither_the_api_nor_an_orm():
    code = (
        "import sys, comm_center_notifier.__main__, comm_center_notifier.runner, "
        "comm_center_notifier.outbox, comm_center_notifier.sender\n"
        "bad = sorted(m for m in sys.modules if m.split('.')[0] in ('sqlalchemy', 'app', 'fastapi', 'alembic'))\n"
        "print(bad)\n"
        "sys.exit(1 if bad else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], check=False, capture_output=True, text=True, cwd=NOTIFIER_DIR
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_notifier_does_not_depend_on_the_api_or_an_orm():
    declared = (NOTIFIER_DIR / "pyproject.toml").read_text().lower()
    for forbidden in ("sqlalchemy", "fastapi", "alembic", "comm-center-api"):
        assert forbidden not in declared
