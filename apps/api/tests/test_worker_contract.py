"""The API and the worker share one file, the worker-facing OpenAPI contract, and agree on the
protocol version. The worker's own tests check its client against the same file."""

from pathlib import Path

from comm_center_worker.protocol import PROTOCOL_VERSION

from app.export_worker_contract import render
from app.routers.worker import PROTOCOL_VERSION as SERVER_PROTOCOL

COMMITTED = Path(__file__).resolve().parents[2] / "worker" / "contract" / "worker-api.json"


def test_the_committed_worker_contract_matches_the_api():
    assert COMMITTED.read_text() == render(), (
        "run: pnpm --filter @comm-center/api gen:worker-contract"
    )


def test_the_worker_and_the_api_agree_on_the_protocol_version():
    assert PROTOCOL_VERSION == SERVER_PROTOCOL
