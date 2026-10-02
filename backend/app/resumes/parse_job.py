import uuid
from collections.abc import Callable

from pydantic import BaseModel

from app.artifacts.extraction import (
    ExtractionError,
    ExtractionLimits,
    ExtractionResult,
    extract_isolated,
)
from app.artifacts.sniff import PDF_MIME, FileKind
from app.artifacts.storage import StorageAdapter
from app.config import Settings
from app.core.logging import get_logger
from app.db.models import ExtractionStatus
from app.db.tenancy import NotFound
from app.jobs.registry import JobContext
from app.resumes.repository import ArtifactRepository, ResumeRepository

log = get_logger(__name__)

PARSE_RESUME_JOB = "parse_resume"

Extractor = Callable[[bytes, FileKind, ExtractionLimits], ExtractionResult]


class ParseResumePayload(BaseModel):
    artifact_id: uuid.UUID
    resume_id: uuid.UUID


def parse_unique_key(artifact_id: uuid.UUID) -> str:
    return f"{PARSE_RESUME_JOB}:{artifact_id}"


def make_parse_resume_handler(
    storage: StorageAdapter, settings: Settings, extractor: Extractor = extract_isolated
) -> Callable[[JobContext, ParseResumePayload], None]:
    limits = ExtractionLimits(
        max_pages=settings.resume_max_pages,
        max_chars=settings.extracted_text_max_chars,
        timeout_seconds=settings.parse_timeout_seconds,
    )

    def handle(context: JobContext, payload: ParseResumePayload) -> None:
        user_id = context.require_user_id()
        try:
            artifact = ArtifactRepository(context.session).get(
                user_id=user_id, id=payload.artifact_id
            )
            resume = ResumeRepository(context.session).get(user_id=user_id, id=payload.resume_id)
        except NotFound:
            log.info("parse_target_missing")
            return
        if resume.artifact_id != artifact.id or artifact.extraction_status is not (
            ExtractionStatus.PENDING
        ):
            log.info("parse_skipped", extraction_status=artifact.extraction_status.value)
            return
        try:
            with storage.open(artifact.storage_key) as handle:
                data = handle.read()
        except FileNotFoundError:
            result = ExtractionResult(ExtractionError.UNREADABLE)
        else:
            kind = FileKind.PDF if artifact.mime_type == PDF_MIME else FileKind.DOCX
            result = extractor(data, kind, limits)
        if result.error is not None:
            artifact.extraction_status = ExtractionStatus.FAILED
            artifact.extraction_error_code = result.error.value
            log.info("resume_parse_failed", error_code=result.error.value)
            return
        artifact.extraction_status = ExtractionStatus.SUCCEEDED
        artifact.extraction_error_code = None
        artifact.extracted_text = result.text
        resume.parsed_outline = (
            None if result.outline is None else result.outline.model_dump(mode="json")
        )
        log.info(
            "resume_parsed",
            line_count=None if result.outline is None else result.outline.line_count,
        )

    return handle
