import re
import zipfile
from dataclasses import dataclass
from enum import StrEnum
from typing import BinaryIO

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

DOCX_MAX_MEMBERS = 1000
DOCX_MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
DOCX_MAX_DOCUMENT_XML_BYTES = 20 * 1024 * 1024
DOCX_MAX_MEMBER_RATIO = 200

MAX_FILENAME_LENGTH = 120
FALLBACK_FILENAME = "resume"

_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


class FileKind(StrEnum):
    PDF = "pdf"
    DOCX = "docx"


class UploadRejected(Exception):
    def __init__(self, status_code: int, code: str) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True)
class Sniffed:
    kind: FileKind
    mime_type: str


def sniff(source: BinaryIO) -> Sniffed:
    source.seek(0)
    head = source.read(5)
    source.seek(0)
    if head == b"%PDF-":
        return Sniffed(FileKind.PDF, PDF_MIME)
    if head[:4] == b"PK\x03\x04":
        check_docx(source)
        return Sniffed(FileKind.DOCX, DOCX_MIME)
    raise UploadRejected(415, "unsupported_file_type")


def check_docx(source: BinaryIO) -> None:
    try:
        with zipfile.ZipFile(source) as archive:
            members = archive.infolist()
    except (zipfile.BadZipFile, NotImplementedError, OSError, ValueError) as exc:
        raise UploadRejected(415, "unsupported_file_type") from exc
    finally:
        source.seek(0)
    names = {member.filename for member in members}
    if "word/document.xml" not in names:
        raise UploadRejected(415, "unsupported_file_type")
    if len(members) > DOCX_MAX_MEMBERS:
        raise UploadRejected(422, "unsafe_document")
    if sum(member.file_size for member in members) > DOCX_MAX_UNCOMPRESSED_BYTES:
        raise UploadRejected(422, "unsafe_document")
    for member in members:
        if member.filename == "word/document.xml" and (
            member.file_size > DOCX_MAX_DOCUMENT_XML_BYTES
        ):
            raise UploadRejected(422, "unsafe_document")
        if member.file_size > 1024 * 1024 and (
            member.file_size > DOCX_MAX_MEMBER_RATIO * max(member.compress_size, 1)
        ):
            raise UploadRejected(422, "unsafe_document")


def sanitize_filename(raw: str | None) -> str:
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = _CONTROL_CHARACTERS.sub("", name).strip().strip(".")
    if len(name) > MAX_FILENAME_LENGTH:
        stem, dot, extension = name.rpartition(".")
        if dot and len(extension) <= 10:
            name = stem[: MAX_FILENAME_LENGTH - len(extension) - 1] + "." + extension
        else:
            name = name[:MAX_FILENAME_LENGTH]
    return name or FALLBACK_FILENAME


def default_label(filename: str) -> str:
    stem, dot, _ = filename.rpartition(".")
    return (stem if dot and stem else filename)[:MAX_FILENAME_LENGTH]
