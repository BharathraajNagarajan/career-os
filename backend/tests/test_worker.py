import signal
import threading
from collections.abc import Callable

from app.config import Settings
from app.worker import install_signal_handlers, run

ReadLogs = Callable[[], list[dict[str, object]]]


def idle() -> bool:
    return False


def test_worker_runs_until_iteration_limit(settings: Settings, read_logs: ReadLogs) -> None:
    iterations = run(settings, threading.Event(), idle, max_iterations=3)

    events = [entry["event"] for entry in read_logs()]
    assert iterations == 3
    assert events[0] == "worker_started"
    assert events[-1] == "worker_stopped"


def test_worker_exits_immediately_when_stopped(settings: Settings) -> None:
    stop = threading.Event()
    stop.set()

    assert run(settings, stop, idle) == 0


def test_worker_sleeps_only_when_idle(settings: Settings) -> None:
    busy_settings = settings.model_copy(update={"worker_poll_interval_seconds": 60})
    results = iter([True, True, True])

    assert run(busy_settings, threading.Event(), lambda: next(results), max_iterations=3) == 3


def test_worker_finishes_current_job_before_stopping(settings: Settings) -> None:
    stop = threading.Event()
    finished: list[bool] = []

    def step() -> bool:
        stop.set()
        finished.append(True)
        return True

    assert run(settings, stop, step) == 1
    assert finished == [True]


def test_worker_survives_step_errors(settings: Settings, read_logs: ReadLogs) -> None:
    def failing() -> bool:
        raise ConnectionError("database unavailable at postgresql://u:p@h/db")

    run(settings, threading.Event(), failing, max_iterations=2)

    failures = [entry for entry in read_logs() if entry["event"] == "worker_step_failed"]
    assert [entry["error_type"] for entry in failures] == ["ConnectionError"] * 2
    assert "postgresql://" not in str(read_logs())


def test_sigterm_requests_graceful_stop() -> None:
    previous = signal.getsignal(signal.SIGTERM)
    stop = threading.Event()
    try:
        install_signal_handlers(stop)
        signal.raise_signal(signal.SIGTERM)
    finally:
        signal.signal(signal.SIGTERM, previous)
        signal.signal(signal.SIGINT, signal.default_int_handler)

    assert stop.is_set()
