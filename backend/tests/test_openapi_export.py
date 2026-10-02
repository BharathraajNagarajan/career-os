from pathlib import Path

from app.openapi_export import render_schema

COMMITTED = Path(__file__).resolve().parents[1] / "openapi.json"


def test_committed_openapi_contract_matches_the_app() -> None:
    assert COMMITTED.read_text(encoding="utf-8") == render_schema()
