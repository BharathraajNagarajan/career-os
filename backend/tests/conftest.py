import io
import json
import os
from collections.abc import Callable

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


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("TEST_ADMIN_DATABASE_URL"):
        return
    if os.environ.get("REQUIRE_DB_TESTS") == "1":
        raise pytest.UsageError("REQUIRE_DB_TESTS=1 but TEST_ADMIN_DATABASE_URL is not set")
    skip_db = pytest.mark.skip(reason="TEST_ADMIN_DATABASE_URL is not set")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip_db)
