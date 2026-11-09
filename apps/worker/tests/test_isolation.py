"""The worker holds no database access and reaches the API only over HTTP (SPECS.md 4.7)."""

import subprocess
import sys
from pathlib import Path

WORKER_DIR = Path(__file__).resolve().parents[1]


def test_importing_the_worker_loads_neither_the_database_nor_the_api_code():
    code = (
        "import sys, comm_center_worker.__main__, comm_center_worker.runner, "
        "comm_center_worker.supervisor, comm_center_worker.outbound, comm_center_worker.inbound, "
        "comm_center_worker.client, comm_center_worker.fake\n"
        "bad = sorted(m for m in sys.modules if m.split('.')[0] in ('sqlalchemy', 'app', 'pymysql', 'fastapi'))\n"
        "print(bad)\n"
        "sys.exit(1 if bad else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], check=False, capture_output=True, text=True, cwd=WORKER_DIR
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_worker_does_not_depend_on_the_database_or_the_api_framework():
    declared = (WORKER_DIR / "pyproject.toml").read_text()
    for forbidden in ("sqlalchemy", "pymysql", "fastapi", "alembic"):
        assert forbidden not in declared.lower()
