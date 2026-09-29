import signal
import threading
from collections.abc import Callable

from app.config import Settings
from app.worker import install_signal_handlers, run

ReadLogs = Callable[[], list[dict[str, object]]]


def test_worker_runs_until_iteration_limit(settings: Settings, read_logs: ReadLogs) -> None:
    iterations = run(settings, threading.Event(), max_iterations=3)

    events = [entry["event"] for entry in read_logs()]
    assert iterations == 3
    assert events[0] == "worker_started"
    assert events[-1] == "worker_stopped"


def test_worker_exits_immediately_when_stopped(settings: Settings) -> None:
    stop = threading.Event()
    stop.set()

    assert run(settings, stop) == 0


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
