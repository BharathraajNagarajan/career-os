import io
import json
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
