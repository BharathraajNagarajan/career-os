import io
import ipaddress
import json
import os
import socket
from collections.abc import Callable
from typing import Any

import pytest

from app.config import Environment, Settings
from app.core.logging import configure_logging


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment=Environment.TEST,
        database_url="postgresql://career:unused@localhost:5432/career_test",
        worker_poll_interval_seconds=0.01,
        log_level="DEBUG",
    )


@pytest.fixture
def log_stream(settings: Settings) -> io.StringIO:
    stream = io.StringIO()
    configure_logging(settings, stream=stream)
    return stream


@pytest.fixture
def read_logs(log_stream: io.StringIO) -> Callable[[], list[dict[str, object]]]:
    def read() -> list[dict[str, object]]:
        return [json.loads(line) for line in log_stream.getvalue().splitlines() if line]

    return read


class NetworkAccessBlocked(RuntimeError):
    pass


def _is_local(address: Any) -> bool:
    if not isinstance(address, tuple) or not address:
        return True
    host = address[0]
    if not isinstance(host, str):
        return True
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def block_outbound_network(monkeypatch: pytest.MonkeyPatch) -> None:
    real_connect = socket.socket.connect

    def guarded_connect(self: socket.socket, address: Any) -> None:
        if not _is_local(address):
            raise NetworkAccessBlocked(f"tests may not reach {address[0]!r}")
        real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("TEST_ADMIN_DATABASE_URL"):
        return
    if os.environ.get("REQUIRE_DB_TESTS") == "1":
        raise pytest.UsageError("REQUIRE_DB_TESTS=1 but TEST_ADMIN_DATABASE_URL is not set")
    skip_db = pytest.mark.skip(reason="TEST_ADMIN_DATABASE_URL is not set")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip_db)
