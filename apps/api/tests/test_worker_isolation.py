"""The worker holds no database access and reaches the API only over HTTP (SPECS.md 4.7)."""

import subprocess
import sys
from pathlib import Path

from app.routers.worker import PROTOCOL_VERSION as SERVER_PROTOCOL
from app.worker.protocol import PROTOCOL_VERSION

API_DIR = Path(__file__).resolve().parents[1]


def test_importing_the_worker_loads_no_database_code():
    code = (
        "import sys, app.worker.__main__, app.worker.runner, app.worker.supervisor, "
        "app.worker.outbound, app.worker.inbound, app.worker.client, app.worker.fake\n"
        "bad = sorted(m for m in sys.modules if m.split('.')[0] == 'sqlalchemy' "
        "or m in ('app.db', 'app.models', 'app.models.base') or m.startswith('app.models.'))\n"
        "print(bad)\n"
        "sys.exit(1 if bad else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], check=False, capture_output=True, text=True, cwd=API_DIR
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_worker_and_the_api_agree_on_the_protocol_version():
    assert PROTOCOL_VERSION == SERVER_PROTOCOL
