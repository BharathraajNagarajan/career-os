import io

import pytest

from app.artifacts import sniff as sniff_module
from app.artifacts.sniff import (
    DOCX_MAX_MEMBERS,
    DOCX_MIME,
    PDF_MIME,
    FileKind,
    UploadRejected,
    default_label,
    sanitize_filename,
    sniff,
)
from tests.synthetic import synthetic_docx, synthetic_pdf, zip_with


def test_pdf_is_detected_by_magic_bytes() -> None:
    result = sniff(io.BytesIO(synthetic_pdf("a")))

    assert (result.kind, result.mime_type) == (FileKind.PDF, PDF_MIME)


def test_docx_is_detected_by_zip_structure() -> None:
    result = sniff(io.BytesIO(synthetic_docx("a")))

    assert (result.kind, result.mime_type) == (FileKind.DOCX, DOCX_MIME)


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"plain text pretending to be a resume",
        b"\xd0\xcf\x11\xe0 legacy office file",
        b"%PD",
        b"PK\x03\x04 broken zip",
        zip_with({"notes.txt": b"hello"}),
        zip_with({"xl/workbook.xml": b"<x/>"}),
    ],
)
def test_other_content_is_unsupported(content: bytes) -> None:
    with pytest.raises(UploadRejected) as error:
        sniff(io.BytesIO(content))

    assert (error.value.status_code, error.value.code) == (415, "unsupported_file_type")


def test_a_docx_with_too_many_members_is_rejected() -> None:
    members = {f"part{index}.xml": b"x" for index in range(DOCX_MAX_MEMBERS)}
    members["word/document.xml"] = b"<w/>"

    with pytest.raises(UploadRejected) as error:
        sniff(io.BytesIO(zip_with(members)))

    assert (error.value.status_code, error.value.code) == (422, "unsafe_document")


def test_a_highly_compressed_member_is_rejected() -> None:
    bomb = zip_with({"word/document.xml": b"<w/>", "word/media/big.bin": b"\x00" * 30_000_000})

    with pytest.raises(UploadRejected) as error:
        sniff(io.BytesIO(bomb))

    assert error.value.code == "unsafe_document"


def test_total_uncompressed_size_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sniff_module, "DOCX_MAX_UNCOMPRESSED_BYTES", 100)
    archive = zip_with({"word/document.xml": b"<w/>", "word/media/a.bin": b"abcdefg" * 30})

    with pytest.raises(UploadRejected) as error:
        sniff(io.BytesIO(archive))

    assert error.value.code == "unsafe_document"


def test_sniff_leaves_the_stream_at_the_start() -> None:
    stream = io.BytesIO(synthetic_docx("a"))

    sniff(stream)

    assert stream.tell() == 0


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("resume.pdf", "resume.pdf"),
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\someone\\cv.docx", "cv.docx"),
        ("na\x00me\x1f.pdf", "name.pdf"),
        ("  ..hidden.pdf ", "hidden.pdf"),
        ("", "resume"),
        (None, "resume"),
        ("///", "resume"),
    ],
)
def test_filenames_are_sanitized(raw: str | None, expected: str) -> None:
    assert sanitize_filename(raw) == expected


def test_long_filenames_are_capped_and_keep_the_extension() -> None:
    cleaned = sanitize_filename("a" * 400 + ".pdf")

    assert len(cleaned) <= 120
    assert cleaned.endswith(".pdf")


def test_default_label_drops_the_extension() -> None:
    assert default_label("Sample Resume v2.pdf") == "Sample Resume v2"
    assert default_label("noextension") == "noextension"
