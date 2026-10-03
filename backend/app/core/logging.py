import logging
import re
import sys
from typing import Any, TextIO

import structlog
from structlog.types import EventDict, Processor, WrappedLogger

from app.config import BaseAppSettings

ALLOWED_FIELDS = frozenset(
    {
        "event",
        "level",
        "timestamp",
        "logger",
        "exception",
        "request_id",
        "correlation_id",
        "job_id",
        "job_kind",
        "attempt",
        "user_id",
        "worker_id",
        "iteration",
        "module",
        "method",
        "route",
        "status_code",
        "duration_ms",
        "outcome",
        "error_code",
        "error_type",
        "count",
        "environment",
        "version",
        "dropped_field_count",
        "run_id",
        "purpose",
        "prompt_id",
        "prompt_version",
        "provider",
        "model",
        "tier",
        "status",
        "input_tokens",
        "output_tokens",
        "cost_usd",
        "latency_ms",
        "review_item_id",
        "proposal_type",
        "opportunity_id",
        "dropped_count",
    }
)

REDACTED = "[REDACTED]"

_PATTERNS = (
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
    re.compile(r"ya29\.[A-Za-z0-9._-]+"),
    re.compile(r"1//[A-Za-z0-9._-]{20,}"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql|redis)(?:\+\w+)?://\S+"),
    re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{40,}(?![A-Za-z0-9_-])"),
)


def redact_text(value: str) -> str:
    for pattern in _PATTERNS:
        value = pattern.sub(REDACTED, value)
    return value


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, bool | int | float) or value is None:
        return value
    return redact_text(str(value))


def drop_unknown_fields(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    unknown = [
        key
        for key in event_dict
        if key not in ALLOWED_FIELDS and key != "exc_info" and not key.startswith("_")
    ]
    for key in unknown:
        del event_dict[key]
    if unknown:
        event_dict["dropped_field_count"] = len(unknown)
    return event_dict


def redact_values(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    for key, value in list(event_dict.items()):
        if key in {"level", "timestamp"} or key.startswith("_"):
            continue
        event_dict[key] = _redact_value(value)
    return event_dict


def _shared_processors() -> list[Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        drop_unknown_fields,
        structlog.processors.format_exc_info,
        redact_values,
    ]


def configure_logging(settings: BaseAppSettings, stream: TextIO | None = None) -> None:
    output = stream or sys.stdout
    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if settings.log_json
        else structlog.dev.ConsoleRenderer(colors=False)
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_shared_processors(),
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    )
    handler = logging.StreamHandler(output)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)

    structlog.configure(
        processors=[
            *_shared_processors(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.stdlib.get_logger(name)
    return logger
