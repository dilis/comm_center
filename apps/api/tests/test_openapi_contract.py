"""The web app's typed client is generated from ``apps/web/src/api/openapi.json``; this fails when
the API changed and the file was not regenerated (``pnpm --filter @comm-center/web gen:api``)."""

from pathlib import Path

from app.export_openapi import render

COMMITTED = Path(__file__).resolve().parents[2] / "web" / "src" / "api" / "openapi.json"


def test_committed_openapi_matches_the_api():
    assert COMMITTED.read_text() == render(), "run: pnpm --filter @comm-center/web gen:api"
