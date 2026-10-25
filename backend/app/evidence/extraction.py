import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.logging import get_logger
from app.db.models import (
    Artifact,
    EngagementType,
    EvidenceClass,
    ExtractionStatus,
    LlmPurpose,
    LlmRun,
    LlmTier,
    ProposalType,
    ReviewItem,
    ReviewSource,
)
from app.db.tenancy import NotFound
from app.evidence.commands import find_skill_by_name
from app.evidence.normalize import clean_name, skill_key
from app.evidence.proposals import ClaimProposal, SkillProposal
from app.jobs.registry import JobContext, PermanentJobError
from app.llm.errors import LlmError
from app.llm.gateway import ModelGateway
from app.llm.prompts.evidence_extract import (
    EVIDENCE_EXTRACT,
    EvidenceExtraction,
    ExtractedClaim,
)
from app.llm.repository import LlmRunRepository
from app.llm.schemas import ManifestEntry
from app.opportunities.normalize import collapse_whitespace
from app.resumes.repository import ResumeRepository
from app.review.handlers import ReviewHandlerRegistry
from app.review.repository import ReviewItemRepository

log = get_logger(__name__)

EXTRACT_EVIDENCE_JOB = "extract_evidence"
RESUME_TEXT_MISSING = "resume_text_missing"
RESUME_UNREADABLE = "resume_unreadable"
MAX_STATEMENT_CHARS = 1000
EARLIEST_DATE = date(1950, 1, 1)
QUOTE_WINDOW_CHARS = 300
ENGAGEMENT_CUES = {
    EngagementType.FULL_TIME: re.compile(r"full[\s-]?time", re.IGNORECASE),
    EngagementType.PART_TIME: re.compile(r"part[\s-]?time", re.IGNORECASE),
    EngagementType.CONTRACT: re.compile(r"\b(contract|contractor|freelance)\b", re.IGNORECASE),
    EngagementType.INTERNSHIP: re.compile(r"\b(intern|interns|internship|co-?op)\b", re.IGNORECASE),
}


class ExtractEvidencePayload(BaseModel):
    resume_id: uuid.UUID


class ResumeNotParsed(Exception):
    pass


def extract_unique_key(resume_id: uuid.UUID) -> str:
    return f"{EXTRACT_EVIDENCE_JOB}:{resume_id}"


@dataclass(frozen=True)
class CleanClaim:
    statement: str
    evidence_class: EvidenceClass
    engagement_type: EngagementType | None
    organization_label: str | None
    start_date: date | None
    end_date: date | None
    skill_names: list[str]
    confidence: Decimal
    rationale: str


@dataclass(frozen=True)
class CleanSkill:
    name: str
    confidence: Decimal
    rationale: str


@dataclass(frozen=True)
class CleanExtraction:
    claims: list[CleanClaim]
    skills: list[CleanSkill]
    dropped_claims: int
    dropped_skills: int
    unsupported_engagement_types: int


def _confidence(value: float) -> Decimal:
    if value != value:
        return Decimal("0.000")
    return Decimal(str(round(max(0.0, min(1.0, value)), 3))).quantize(Decimal("0.001"))


def parse_date(raw: str | None, *, today: date) -> date | None:
    if not raw:
        return None
    parts = raw.strip().split("-")
    try:
        numbers = [int(part) for part in parts]
        if len(numbers) > 3 or any(len(part) not in (2, 4) for part in parts):
            return None
        parsed = date(
            numbers[0], numbers[1] if len(numbers) > 1 else 1, numbers[2] if len(numbers) > 2 else 1
        )
    except ValueError:
        return None
    return parsed if EARLIEST_DATE <= parsed <= today + timedelta(days=366) else None


def _near(haystack: str, first: str, second: str) -> bool:
    starts = [match.start() for match in re.finditer(re.escape(second), haystack, re.IGNORECASE)]
    return any(
        abs(match.start() - start) <= QUOTE_WINDOW_CHARS
        for match in re.finditer(re.escape(first), haystack, re.IGNORECASE)
        for start in starts
    )


def supported_engagement(
    claim: ExtractedClaim, statement: str, haystack: str
) -> EngagementType | None:
    claimed = EngagementType(claim.engagement_type)
    if claim.evidence_class != "professional":
        return None
    cue = ENGAGEMENT_CUES.get(claimed)
    quote = collapse_whitespace(claim.engagement_quote or "")
    if cue is None or not quote or quote.casefold() not in haystack.casefold():
        return EngagementType.UNSPECIFIED
    if cue.search(quote) is None:
        return EngagementType.UNSPECIFIED
    return claimed if _near(haystack, statement, quote) else EngagementType.UNSPECIFIED


def clean_extraction(
    raw: EvidenceExtraction,
    resume_text: str,
    *,
    max_claims: int,
    max_skills: int,
    today: date | None = None,
) -> CleanExtraction:
    haystack = collapse_whitespace(resume_text)
    folded = haystack.casefold()
    day = today or datetime.now(UTC).date()
    claims: dict[str, CleanClaim] = {}
    unsupported = 0
    for item in raw.claims:
        statement = collapse_whitespace(item.statement)
        if not statement or len(statement) > MAX_STATEMENT_CHARS or statement not in haystack:
            continue
        engagement = supported_engagement(item, statement, haystack)
        if (
            item.evidence_class == "professional"
            and EngagementType(item.engagement_type) is not EngagementType.UNSPECIFIED
            and engagement is EngagementType.UNSPECIFIED
        ):
            unsupported += 1
        organization = collapse_whitespace(item.organization or "")[:200]
        start, end = parse_date(item.start_date, today=day), parse_date(item.end_date, today=day)
        if start and end and end < start:
            end = None
        names: dict[str, str] = {}
        for skill in item.skills:
            name = clean_name(skill)
            key = skill_key(name)
            if key and name.casefold() in folded:
                names.setdefault(key, name)
        claims.setdefault(
            statement,
            CleanClaim(
                statement=statement,
                evidence_class=EvidenceClass(item.evidence_class),
                engagement_type=engagement,
                organization_label=organization
                if organization and organization in haystack
                else None,
                start_date=start,
                end_date=end,
                skill_names=list(names.values()),
                confidence=_confidence(item.confidence),
                rationale=collapse_whitespace(item.rationale),
            ),
        )
    skills: dict[str, CleanSkill] = {}
    for extracted in raw.skills:
        name = clean_name(extracted.name)
        key = skill_key(name)
        if key and name.casefold() in folded:
            skills.setdefault(
                key,
                CleanSkill(
                    name=name,
                    confidence=_confidence(extracted.confidence),
                    rationale=collapse_whitespace(extracted.rationale),
                ),
            )
    kept_claims = list(claims.values())[:max_claims]
    kept_skills = list(skills.values())[:max_skills]
    return CleanExtraction(
        claims=kept_claims,
        skills=kept_skills,
        dropped_claims=len(raw.claims) - len(kept_claims),
        dropped_skills=len(raw.skills) - len(kept_skills),
        unsupported_engagement_types=unsupported,
    )


def stored_extraction(run: LlmRun) -> EvidenceExtraction | None:
    try:
        return EvidenceExtraction.model_validate((run.output or {})["data"])
    except (KeyError, TypeError, ValidationError):
        return None


def resume_text(session: Session, *, user_id: uuid.UUID, artifact_id: uuid.UUID) -> str | None:
    return session.scalars(
        select(Artifact.extracted_text).where(
            Artifact.user_id == user_id, Artifact.id == artifact_id
        )
    ).one_or_none()


def create_proposals(
    session: Session,
    *,
    user_id: uuid.UUID,
    resume_id: uuid.UUID,
    run_id: uuid.UUID,
    clean: CleanExtraction,
    registry: ReviewHandlerRegistry,
) -> tuple[int, int, int]:
    reviews = ReviewItemRepository(session)
    already = session.scalar(
        select(func.count())
        .select_from(ReviewItem)
        .where(ReviewItem.user_id == user_id, ReviewItem.llm_run_id == run_id)
    )
    if already:
        return 0, 0, 0
    claim_count = 0
    for claim in clean.claims:
        reviews.create(
            user_id=user_id,
            registry=registry,
            source=ReviewSource.EXTRACTION,
            proposal_type=ProposalType.CLAIM,
            payload=ClaimProposal(
                statement=claim.statement,
                evidence_class=claim.evidence_class,
                engagement_type=claim.engagement_type,
                start_date=claim.start_date,
                end_date=claim.end_date,
                organization_label=claim.organization_label,
                skill_names=claim.skill_names,
                resume_id=resume_id,
            ),
            confidence=claim.confidence,
            rationale=claim.rationale or None,
            evidence_ref_id=resume_id,
            llm_run_id=run_id,
        )
        claim_count += 1
    skill_count = linked = 0
    for skill in clean.skills:
        if find_skill_by_name(session, user_id=user_id, name=skill.name) is not None:
            linked += 1
            continue
        reviews.create(
            user_id=user_id,
            registry=registry,
            source=ReviewSource.EXTRACTION,
            proposal_type=ProposalType.SKILL,
            payload=SkillProposal(name=skill.name, resume_id=resume_id),
            confidence=skill.confidence,
            rationale=skill.rationale or None,
            evidence_ref_id=resume_id,
            llm_run_id=run_id,
        )
        skill_count += 1
    return claim_count, skill_count, linked


def make_extract_evidence_handler(
    gateway: ModelGateway, settings: Settings, registry: ReviewHandlerRegistry
) -> Callable[[JobContext, ExtractEvidencePayload], None]:
    def handle(context: JobContext, payload: ExtractEvidencePayload) -> None:
        user_id = context.require_user_id()
        session = context.session
        try:
            resume, artifact = ResumeRepository(session).get_with_artifact(
                user_id=user_id, id=payload.resume_id
            )
        except NotFound:
            log.info("evidence_target_missing")
            return
        if artifact.extraction_status is ExtractionStatus.PENDING:
            raise ResumeNotParsed
        text = resume_text(session, user_id=user_id, artifact_id=artifact.id)
        if artifact.extraction_status is ExtractionStatus.FAILED:
            raise PermanentJobError(RESUME_UNREADABLE)
        if not text or not text.strip():
            raise PermanentJobError(RESUME_TEXT_MISSING)
        resume_id, artifact_id = resume.id, artifact.id

        def apply(output: EvidenceExtraction, run_id: uuid.UUID) -> None:
            clean = clean_extraction(
                output,
                text,
                max_claims=settings.evidence_max_claims,
                max_skills=settings.evidence_max_skills,
            )
            claims, skills, linked = create_proposals(
                session,
                user_id=user_id,
                resume_id=resume_id,
                run_id=run_id,
                clean=clean,
                registry=registry,
            )
            log.info(
                "evidence_extracted",
                resume_id=str(resume_id),
                run_id=str(run_id),
                claim_count=claims,
                skill_count=skills,
                linked_count=linked,
                dropped_count=clean.dropped_claims,
                unsupported_count=clean.unsupported_engagement_types,
            )

        reusable = LlmRunRepository(session).find_settled_structured(
            user_id=user_id,
            purpose=LlmPurpose.EXTRACT_RESUME,
            prompt_id=EVIDENCE_EXTRACT,
            artifact_id=artifact_id,
            exclude_run_id=None,
        )
        stored = None if reusable is None else stored_extraction(reusable)
        if reusable is not None and stored is not None:
            log.info("evidence_extraction_reused", run_id=str(reusable.id))
            apply(stored, reusable.id)
            return
        session.commit()
        try:
            result = gateway.structured(
                user_id=user_id,
                purpose=LlmPurpose.EXTRACT_RESUME,
                prompt_id=EVIDENCE_EXTRACT,
                tier=LlmTier.FAST,
                output_type=EvidenceExtraction,
                variables={"resume": text},
                context_manifest=[
                    ManifestEntry(entity_type="artifact", entity_id=artifact_id, version=0)
                ],
                max_output_tokens=settings.evidence_extraction_max_output_tokens,
            )
        except LlmError as exc:
            log.info("evidence_extraction_failed", resume_id=str(resume_id), error_code=exc.code)
            raise PermanentJobError(exc.code) from exc
        apply(result.output, result.run_id)

    return handle
