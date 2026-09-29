import os
import signal
import socket
import threading
from types import FrameType

from app import __version__
from app.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger

log = get_logger(__name__)


def worker_identity() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


def run(settings: Settings, stop: threading.Event, max_iterations: int | None = None) -> int:
    worker_id = worker_identity()
    log.info(
        "worker_started",
        worker_id=worker_id,
        environment=settings.environment.value,
        version=__version__,
    )
    iterations = 0
    while not stop.is_set():
        if max_iterations is not None and iterations >= max_iterations:
            break
        iterations += 1
        log.debug("worker_idle", worker_id=worker_id, iteration=iterations)
        stop.wait(settings.worker_poll_interval_seconds)
    log.info("worker_stopped", worker_id=worker_id, count=iterations)
    return iterations


def install_signal_handlers(stop: threading.Event) -> None:
    def request_stop(signum: int, _: FrameType | None) -> None:
        log.info("worker_stop_requested", outcome=signal.Signals(signum).name)
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)


def main() -> None:
    settings = get_settings()
    configure_logging(settings)
    stop = threading.Event()
    install_signal_handlers(stop)
    run(settings, stop)


if __name__ == "__main__":
    main()
