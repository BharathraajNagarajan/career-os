import os
import signal
import socket
import threading
from collections.abc import Callable
from types import FrameType

from app import __version__
from app.artifacts.storage import FilesystemStorage
from app.config import Settings, get_settings
from app.core.db import create_db_engine, session_factory
from app.core.logging import configure_logging, get_logger
from app.jobs.handlers import register_job_handlers
from app.jobs.registry import job_registry
from app.jobs.runner import JobRunner
from app.llm.factory import build_gateway

log = get_logger(__name__)


def worker_identity() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


def run(
    settings: Settings,
    stop: threading.Event,
    step: Callable[[], bool],
    max_iterations: int | None = None,
    worker_id: str | None = None,
) -> int:
    worker_id = worker_id or worker_identity()
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
        try:
            busy = step()
        except Exception as exc:
            log.error("worker_step_failed", worker_id=worker_id, error_type=type(exc).__name__)
            busy = False
        if not busy:
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
    worker_id = worker_identity()
    engine = create_db_engine(settings.database_url)
    sessions = session_factory(engine)
    register_job_handlers(
        job_registry,
        storage=FilesystemStorage(settings.artifact_storage_dir),
        settings=settings,
        gateway=build_gateway(settings, sessions),
    )
    runner = JobRunner(sessions, job_registry, settings, worker_id)
    try:
        run(settings, stop, runner.run_once, worker_id=worker_id)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
