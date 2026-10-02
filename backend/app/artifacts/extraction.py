import io
import multiprocessing
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.artifacts.outline import MAX_HEADING_CHARS, ParsedOutline, build_outline
from app.artifacts.sniff import FileKind

TERMINATE_GRACE_SECONDS = 5


class ExtractionError(StrEnum):
    TOO_MANY_PAGES = "too_many_pages"
    ENCRYPTED = "encrypted"
    UNREADABLE = "unreadable"
    PARSE_TIMEOUT = "parse_timeout"


class ParseFailure(Exception):
    def __init__(self, code: ExtractionError) -> None:
        super().__init__(code.value)
        self.code = code


@dataclass(frozen=True)
class ExtractionLimits:
    max_pages: int
    max_chars: int
    timeout_seconds: float


@dataclass(frozen=True)
class ExtractionResult:
    error: ExtractionError | None
    text: str | None = None
    outline: ParsedOutline | None = None


def extract_pdf(data: bytes, max_pages: int) -> tuple[str, list[str]]:
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ParseFailure(ExtractionError.ENCRYPTED)
        if len(reader.pages) > max_pages:
            raise ParseFailure(ExtractionError.TOO_MANY_PAGES)
        pages = [page.extract_text() or "" for page in reader.pages]
    except ParseFailure:
        raise
    except (PyPdfError, ValueError, KeyError, TypeError, AttributeError, RecursionError) as exc:
        raise ParseFailure(ExtractionError.UNREADABLE) from exc
    return "\n".join(pages), []


def _cell_text(cells: Any) -> str:
    seen: list[Any] = []
    parts: list[str] = []
    for cell in cells:
        if any(cell._tc is other for other in seen):
            continue
        seen.append(cell._tc)
        text = cell.text.strip()
        if text:
            parts.append(text)
    return " | ".join(parts)


def _docx_lines(document: Any) -> Iterator[tuple[str, bool]]:
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    for item in document.iter_inner_content():
        if isinstance(item, Paragraph):
            style = (item.style.name or "") if item.style is not None else ""
            yield item.text, style.lower().startswith("heading")
        elif isinstance(item, Table):
            for row in item.rows:
                yield _cell_text(row.cells), False


def extract_docx(data: bytes) -> tuple[str, list[str]]:
    from docx import Document

    try:
        document = Document(io.BytesIO(data))
        lines = list(_docx_lines(document))
    except Exception as exc:
        raise ParseFailure(ExtractionError.UNREADABLE) from exc
    headings = [
        text.strip()[:MAX_HEADING_CHARS] for text, styled in lines if styled and text.strip()
    ]
    return "\n".join(text for text, _ in lines), headings


def extract_text(data: bytes, kind: FileKind, limits: ExtractionLimits) -> ExtractionResult:
    try:
        if kind is FileKind.PDF:
            text, headings = extract_pdf(data, limits.max_pages)
        else:
            text, headings = extract_docx(data)
    except ParseFailure as failure:
        return ExtractionResult(failure.code)
    text = text[: limits.max_chars]
    if not text.strip():
        return ExtractionResult(ExtractionError.UNREADABLE)
    return ExtractionResult(None, text, build_outline(text, headings))


def _child_main(
    connection: Any, data: bytes, kind: FileKind, max_pages: int, max_chars: int
) -> None:
    limits = ExtractionLimits(max_pages, max_chars, 0)
    try:
        result = extract_text(data, kind, limits)
        payload: dict[str, Any] = {
            "error": None if result.error is None else result.error.value,
            "text": result.text,
            "outline": None if result.outline is None else result.outline.model_dump(mode="json"),
        }
    except BaseException:
        payload = {"error": ExtractionError.UNREADABLE.value, "text": None, "outline": None}
    connection.send(payload)
    connection.close()


def extract_isolated(data: bytes, kind: FileKind, limits: ExtractionLimits) -> ExtractionResult:
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_child_main,
        args=(sender, data, kind, limits.max_pages, limits.max_chars),
        daemon=True,
    )
    process.start()
    sender.close()
    try:
        if not receiver.poll(limits.timeout_seconds):
            return ExtractionResult(ExtractionError.PARSE_TIMEOUT)
        try:
            payload = receiver.recv()
        except (EOFError, OSError):
            return ExtractionResult(ExtractionError.UNREADABLE)
    finally:
        receiver.close()
        if process.is_alive():
            process.terminate()
            process.join(TERMINATE_GRACE_SECONDS)
            if process.is_alive():
                process.kill()
        process.join()
        process.close()
    error = None if payload["error"] is None else ExtractionError(payload["error"])
    outline = (
        None if payload["outline"] is None else ParsedOutline.model_validate(payload["outline"])
    )
    return ExtractionResult(error, payload["text"], outline)
