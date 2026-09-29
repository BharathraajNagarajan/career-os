import uuid
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.config import Environment, Settings
from app.main import create_app

ReadLogs = Callable[[], list[dict[str, object]]]


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = create_app(settings)

    @app.get("/items/{item_id}")
    def item(item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    return TestClient(app)


def test_healthz_returns_ok(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_response_carries_generated_request_id(client: TestClient) -> None:
    response = client.get("/healthz")

    assert uuid.UUID(response.headers["X-Request-ID"])


def test_valid_incoming_request_id_is_echoed(client: TestClient) -> None:
    response = client.get("/healthz", headers={"X-Request-ID": "client-req-1234"})

    assert response.headers["X-Request-ID"] == "client-req-1234"


def test_invalid_incoming_request_id_is_replaced(client: TestClient) -> None:
    response = client.get("/healthz", headers={"X-Request-ID": "bad id with spaces"})

    assert response.headers["X-Request-ID"] != "bad id with spaces"
    assert uuid.UUID(response.headers["X-Request-ID"])


def test_request_log_uses_route_template_not_raw_path(
    client: TestClient, read_logs: ReadLogs
) -> None:
    client.get("/items/person@example.com")

    completed = [entry for entry in read_logs() if entry["event"] == "request_completed"]

    assert completed[-1]["route"] == "/items/{item_id}"
    assert completed[-1]["status_code"] == 200
    assert "person@example.com" not in str(completed)


def test_unmatched_route_is_logged_without_path(client: TestClient, read_logs: ReadLogs) -> None:
    response = client.get("/does-not-exist/secret-path")

    completed = [entry for entry in read_logs() if entry["event"] == "request_completed"]

    assert response.status_code == 404
    assert completed[-1]["route"] == "unmatched"
    assert "secret-path" not in str(completed)


def test_docs_disabled_in_production(settings: Settings) -> None:
    production = settings.model_copy(update={"environment": Environment.PRODUCTION})

    response = TestClient(create_app(production)).get("/docs")

    assert response.status_code == 404
