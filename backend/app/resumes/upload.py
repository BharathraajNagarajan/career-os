import hashlib
import tempfile
from dataclasses import dataclass, field
from typing import Any, BinaryIO

from fastapi import Request
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import MultipartParser, parse_options_header

from app.core.errors import ApiError

FILE_FIELD = b"file"
FRAMING_ALLOWANCE = 64 * 1024
MAX_FIELD_BYTES = 4096
MEMORY_SPOOL_BYTES = 1024 * 1024
MAX_HEADER_BYTES = 8192


@dataclass
class ReceivedUpload:
    spool: BinaryIO
    size: int
    sha256: bytes
    filename: str | None
    fields: dict[str, str]


@dataclass
class _Collector:
    max_bytes: int
    spool: Any = field(default_factory=lambda: tempfile.SpooledTemporaryFile(MEMORY_SPOOL_BYTES))  # noqa: SIM115
    hasher: Any = field(default_factory=hashlib.sha256)
    size: int = 0
    filename: str | None = None
    has_file: bool = False
    fields: dict[str, str] = field(default_factory=dict)
    _header_name: bytes = b""
    _header_value: bytes = b""
    _headers: dict[bytes, bytes] = field(default_factory=dict)
    _part: str = "ignored"
    _field_name: str = ""
    _field_buffer: bytes = b""

    def on_part_begin(self) -> None:
        self._headers = {}
        self._header_name = b""
        self._header_value = b""
        self._part = "ignored"

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._header_name += data[start:end]
        self._guard_header(self._header_name)

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._header_value += data[start:end]
        self._guard_header(self._header_value)

    def on_header_end(self) -> None:
        self._headers[self._header_name.lower()] = self._header_value
        self._header_name = b""
        self._header_value = b""

    def on_headers_finished(self) -> None:
        disposition = self._headers.get(b"content-disposition")
        if disposition is None:
            raise ApiError(400, "invalid_upload")
        _, params = parse_options_header(disposition)
        name = params.get(b"name", b"")
        raw_filename = params.get(b"filename")
        if name == FILE_FIELD and raw_filename is not None:
            if self.has_file:
                raise ApiError(400, "invalid_upload")
            self.has_file = True
            self._part = "file"
            self.filename = raw_filename.decode("utf-8", errors="replace")
        elif raw_filename is None:
            self._part = "field"
            self._field_name = name.decode("utf-8", errors="replace")
            self._field_buffer = b""
        else:
            raise ApiError(400, "invalid_upload")

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        chunk = data[start:end]
        if self._part == "file":
            self.size += len(chunk)
            if self.size > self.max_bytes:
                raise ApiError(413, "resume_too_large")
            self.hasher.update(chunk)
            self.spool.write(chunk)
        elif self._part == "field":
            self._field_buffer += chunk
            if len(self._field_buffer) > MAX_FIELD_BYTES:
                raise ApiError(400, "invalid_upload")

    def on_part_end(self) -> None:
        if self._part == "field":
            self.fields[self._field_name] = self._field_buffer.decode("utf-8", errors="replace")

    @staticmethod
    def _guard_header(value: bytes) -> None:
        if len(value) > MAX_HEADER_BYTES:
            raise ApiError(400, "invalid_upload")

    def callbacks(self) -> Any:
        return {
            "on_part_begin": self.on_part_begin,
            "on_header_field": self.on_header_field,
            "on_header_value": self.on_header_value,
            "on_header_end": self.on_header_end,
            "on_headers_finished": self.on_headers_finished,
            "on_part_data": self.on_part_data,
            "on_part_end": self.on_part_end,
        }


async def receive_upload(request: Request, *, max_bytes: int) -> ReceivedUpload:
    content_type, options = parse_options_header(request.headers.get("content-type", ""))
    boundary = options.get(b"boundary")
    if content_type != b"multipart/form-data" or not boundary:
        raise ApiError(400, "invalid_upload")
    body_limit = max_bytes + FRAMING_ALLOWANCE
    try:
        declared = int(request.headers.get("content-length", "0"))
    except ValueError as exc:
        raise ApiError(400, "invalid_upload") from exc
    if declared > body_limit:
        raise ApiError(413, "resume_too_large")
    collector = _Collector(max_bytes)
    parser = MultipartParser(boundary, collector.callbacks())
    received = 0
    try:
        async for chunk in request.stream():
            received += len(chunk)
            if received > body_limit:
                raise ApiError(413, "resume_too_large")
            parser.write(chunk)
        parser.finalize()
    except MultipartParseError as exc:
        collector.spool.close()
        raise ApiError(400, "invalid_upload") from exc
    except BaseException:
        collector.spool.close()
        raise
    if not collector.has_file:
        collector.spool.close()
        raise ApiError(422, "file_required")
    return ReceivedUpload(
        spool=collector.spool,
        size=collector.size,
        sha256=collector.hasher.digest(),
        filename=collector.filename,
        fields=collector.fields,
    )
