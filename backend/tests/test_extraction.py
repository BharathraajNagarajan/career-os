import io

import pytest
from pypdf import PdfReader, PdfWriter

from app.artifacts.extraction import (
    ExtractionError,
    ExtractionLimits,
    extract_isolated,
    extract_text,
)
from app.artifacts.outline import MAX_SECTIONS, build_outline, looks_like_heading
from app.artifacts.sniff import FileKind
from tests.synthetic import make_pdf, synthetic_docx, synthetic_pdf

LIMITS = ExtractionLimits(max_pages=3, max_chars=100_000, timeout_seconds=30)


def test_pdf_text_and_outline_are_extracted_without_a_model() -> None:
    result = extract_text(synthetic_pdf("one"), FileKind.PDF, LIMITS)

    assert result.error is None
    assert result.text is not None
    assert "Synthetic engineer" in result.text
    assert result.outline is not None
    assert [section.heading for section in result.outline.sections] == [
        "SUMMARY",
        "Experience",
        "Skills:",
        "Education",
    ]
    assert result.outline.line_count == 10


def test_docx_headings_come_from_styles_and_tables_are_included() -> None:
    result = extract_text(synthetic_docx("one"), FileKind.DOCX, LIMITS)

    assert result.error is None
    assert result.text is not None
    assert "Widgets | Gadgets" in result.text
    assert result.outline is not None
    assert [section.heading for section in result.outline.sections] == [
        "Summary",
        "Work History",
        "Education",
    ]


def test_pdf_with_too_many_pages_fails() -> None:
    pages = [[f"Page {number}"] for number in range(4)]

    result = extract_text(make_pdf(pages), FileKind.PDF, LIMITS)

    assert result.error is ExtractionError.TOO_MANY_PAGES
    assert result.text is None


def test_encrypted_pdf_fails() -> None:
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(synthetic_pdf("one"))))
    writer.encrypt("synthetic-password")
    buffer = io.BytesIO()
    writer.write(buffer)

    result = extract_text(buffer.getvalue(), FileKind.PDF, LIMITS)

    assert result.error is ExtractionError.ENCRYPTED


@pytest.mark.parametrize(
    ("kind", "data"),
    [
        (FileKind.PDF, b"%PDF-1.4 this is not really a pdf"),
        (FileKind.DOCX, b"PK\x03\x04 not a real archive"),
    ],
)
def test_corrupt_documents_are_unreadable(kind: FileKind, data: bytes) -> None:
    assert extract_text(data, kind, LIMITS).error is ExtractionError.UNREADABLE


def test_a_pdf_without_text_is_unreadable() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)

    assert extract_text(buffer.getvalue(), FileKind.PDF, LIMITS).error is (
        ExtractionError.UNREADABLE
    )


def test_text_is_capped_at_the_character_limit() -> None:
    limits = ExtractionLimits(max_pages=3, max_chars=40, timeout_seconds=30)

    result = extract_text(synthetic_pdf("one"), FileKind.PDF, limits)

    assert result.text is not None
    assert len(result.text) == 40
    assert result.outline is not None
    assert result.outline.char_count == 40


def test_isolated_extraction_returns_the_same_result_from_a_child_process() -> None:
    direct = extract_text(synthetic_docx("two"), FileKind.DOCX, LIMITS)

    isolated = extract_isolated(synthetic_docx("two"), FileKind.DOCX, LIMITS)

    assert isolated == direct


def test_isolated_extraction_reports_child_failures_as_errors() -> None:
    result = extract_isolated(synthetic_pdf("three"), FileKind.PDF, LIMITS)

    assert result.error is None

    failed = extract_isolated(b"%PDF-1.4 garbage", FileKind.PDF, LIMITS)
    assert failed.error is ExtractionError.UNREADABLE


def test_isolated_extraction_is_terminated_at_the_timeout() -> None:
    limits = ExtractionLimits(max_pages=3, max_chars=1000, timeout_seconds=0.01)

    result = extract_isolated(synthetic_pdf("four"), FileKind.PDF, limits)

    assert result.error is ExtractionError.PARSE_TIMEOUT


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("EXPERIENCE", True),
        ("Skills:", True),
        ("Education", True),
        ("Professional Experience", True),
        ("Sample Person Name", False),
        ("Built several widgets for customers.", False),
        ("A very long line that is certainly not a heading but ends in a colon so", False),
        ("ab", False),
        (":", False),
    ],
)
def test_heading_heuristics(line: str, expected: bool) -> None:
    assert looks_like_heading(line) is expected


def test_outline_ranges_cover_every_line_after_the_first_heading() -> None:
    outline = build_outline("Intro line\nSKILLS\nPython\nSQL\nPROJECTS\nOne project\n")

    assert [(s.heading, s.start_line, s.end_line) for s in outline.sections] == [
        ("SKILLS", 2, 4),
        ("PROJECTS", 5, 6),
    ]
    assert outline.line_count == 6
    assert outline.schema_version == 1


def test_outline_section_count_is_bounded() -> None:
    text = "\n".join(f"SECTION {number}\nbody" for number in range(MAX_SECTIONS + 20))

    assert len(build_outline(text).sections) == MAX_SECTIONS
