import logging
import uuid
from collections.abc import Callable

import pytest

from app.core.logging import REDACTED, get_logger, redact_text

ReadLogs = Callable[[], list[dict[str, object]]]


@pytest.mark.usefixtures("log_stream")
def test_unknown_fields_are_dropped_and_counted(read_logs: ReadLogs) -> None:
    get_logger("test").info("resume_parsed", request_id="abc12345", resume_text="Senior engineer")

    [entry] = read_logs()

    assert entry["event"] == "resume_parsed"
    assert entry["request_id"] == "abc12345"
    assert "resume_text" not in entry
    assert entry["dropped_field_count"] == 1


@pytest.mark.usefixtures("log_stream")
def test_allowed_fields_pass_through(read_logs: ReadLogs) -> None:
    user_id = str(uuid.uuid4())
    get_logger("test").info("request_completed", user_id=user_id, status_code=200, duration_ms=1.5)

    [entry] = read_logs()

    assert entry["user_id"] == user_id
    assert entry["status_code"] == 200
    assert entry["duration_ms"] == 1.5
    assert "dropped_field_count" not in entry


@pytest.mark.usefixtures("log_stream")
def test_wake_action_fields_pass_through(read_logs: ReadLogs) -> None:
    action_id = str(uuid.uuid4())
    get_logger("test").info("wake_action_handled", action_id=action_id, woken=True)

    [entry] = read_logs()

    assert entry["action_id"] == action_id
    assert entry["woken"] is True
    assert "dropped_field_count" not in entry


@pytest.mark.parametrize(
    "secret",
    [
        "person@example.com",
        "Bearer abc.def-ghi_jkl",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signaturepart",
        "ya29.a0AfH6SMBexampletoken",
        "1//0gexampleRefreshTokenValue123456",
        "postgresql://career:pw@db:5432/career",
        "sk-" + "a" * 48,
    ],
)
def test_redact_text_masks_sensitive_values(secret: str) -> None:
    redacted = redact_text(f"value={secret} end")

    assert REDACTED in redacted
    assert secret not in redacted


def test_redact_text_keeps_uuids_and_plain_words() -> None:
    value = f"user {uuid.uuid4()} completed step"

    assert redact_text(value) == value


@pytest.mark.usefixtures("log_stream")
def test_event_message_is_redacted(read_logs: ReadLogs) -> None:
    get_logger("test").info("contact person@example.com replied")

    [entry] = read_logs()

    assert "person@example.com" not in str(entry)
    assert REDACTED in str(entry["event"])


@pytest.mark.usefixtures("log_stream")
def test_exception_text_is_redacted(read_logs: ReadLogs) -> None:
    try:
        raise ValueError("token ya29.a0SuperSecretAccessToken for person@example.com")
    except ValueError:
        get_logger("test").exception("sync_failed", error_type="ValueError")

    [entry] = read_logs()

    exception = str(entry["exception"])
    assert "ValueError" in exception
    assert "SuperSecretAccessToken" not in exception
    assert "person@example.com" not in exception


@pytest.mark.usefixtures("log_stream")
def test_stdlib_loggers_use_the_same_pipeline(read_logs: ReadLogs) -> None:
    logging.getLogger("uvicorn.error").warning("bind failed for person@example.com")

    [entry] = read_logs()

    assert entry["logger"] == "uvicorn.error"
    assert "person@example.com" not in str(entry)
