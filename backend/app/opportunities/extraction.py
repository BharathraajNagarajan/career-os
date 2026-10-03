import uuid
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import Settings
from app.core.logging import get_logger
from app.db.models import (
    Actor,
    AggregateType,
    ExtractionStatus,
    LlmPurpose,
    LlmTier,
    Opportunity,
    Qualification,
    QualificationCategory,
    QualificationKind,
    QualificationOrigin,
    WorkplaceType,
)
from app.db.tenancy import NotFound
from app.jobs.registry import JobContext
from app.llm.errors import LlmError
from app.llm.gateway import ModelGateway
from app.llm.prompts.jd_extract import JD_EXTRACT, JdExtraction
from app.llm.schemas import ManifestEntry
from app.opportunities.company_service import MAX_NAME_CHARS, resolve_company
from app.opportunities.countries import ISO_3166_ALPHA2
from app.opportunities.events import OPPORTUNITY_EXTRACTED, OpportunityExtracted, record_event
from app.opportunities.jobs import ExtractJdPayload
from app.opportunities.normalize import (
    clamp_min_years,
    collapse_whitespace,
    normalize_domain,
    normalize_skill_keys,
)
from app.opportunities.repository import OpportunityRepository, QualificationRepository
from app.opportunities.schemas import (
    MAX_LOCATION_ITEMS,
    LocationItem,
    Locations,
    clean_optional_text,
)

log = get_logger(__name__)

JD_TEXT_MISSING = "jd_text_missing"
MAX_QUALIFICATION_CHARS = 1000


@dataclass(frozen=True)
class CleanQualification:
    kind: QualificationKind
    text_verbatim: str
    category: QualificationCategory
    skill_keys: list[str]
    min_years: int | None
    is_hard_constraint: bool


@dataclass(frozen=True)
class CleanExtraction:
    company_name: str | None
    company_domain: str | None
    title: str | None
    team: str | None
    external_job_id: str | None
    location_text: str | None
    locations: Locations
    workplace_type: WorkplaceType
    qualifications: list[CleanQualification]
    dropped_qualifications: int


def _clean_locations(raw: JdExtraction) -> Locations:
    items: list[LocationItem] = []
    for location in raw.locations:
        country = None if location.country is None else location.country.strip().upper()
        item = LocationItem(
            city=clean_optional_text(location.city),
            region=clean_optional_text(location.region),
            country=country if country in ISO_3166_ALPHA2 else None,
        )
        if item.city or item.region or item.country:
            items.append(item)
    return Locations(items=items[:MAX_LOCATION_ITEMS])


def clean_extraction(raw: JdExtraction, jd_text: str) -> CleanExtraction:
    haystack = collapse_whitespace(jd_text)
    kept: dict[str, CleanQualification] = {}
    for item in raw.qualifications:
        text = collapse_whitespace(item.text_verbatim)
        if not text or len(text) > MAX_QUALIFICATION_CHARS or text not in haystack:
            continue
        kept.setdefault(
            text,
            CleanQualification(
                kind=QualificationKind(item.kind),
                text_verbatim=text,
                category=QualificationCategory(item.category),
                skill_keys=normalize_skill_keys(item.skill_keys),
                min_years=clamp_min_years(item.min_years),
                is_hard_constraint=item.is_hard_constraint,
            ),
        )
    company_name = clean_optional_text(raw.company_name)
    return CleanExtraction(
        company_name=None if company_name is None else company_name[:MAX_NAME_CHARS],
        company_domain=None if raw.company_domain is None else normalize_domain(raw.company_domain),
        title=clean_optional_text(raw.title),
        team=clean_optional_text(raw.team),
        external_job_id=clean_optional_text(raw.external_job_id),
        location_text=clean_optional_text(raw.location_text),
        locations=_clean_locations(raw),
        workplace_type=WorkplaceType(raw.workplace_type),
        qualifications=list(kept.values()),
        dropped_qualifications=len(raw.qualifications) - len(kept),
    )


def _mark_failed(
    session: Session, *, user_id: uuid.UUID, opportunity_id: uuid.UUID, code: str
) -> None:
    repository = OpportunityRepository(session)
    opportunity = repository.lock(user_id=user_id, id=opportunity_id)
    if opportunity.extraction_status is ExtractionStatus.PENDING:
        repository.mark_failed(user_id=user_id, id=opportunity.id, error_code=code)
    log.info("jd_extraction_failed", opportunity_id=str(opportunity_id), error_code=code)


def apply_extraction(
    session: Session,
    *,
    user_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    clean: CleanExtraction,
    run_id: uuid.UUID,
) -> bool:
    opportunities = OpportunityRepository(session)
    qualifications = QualificationRepository(session)
    opportunity = opportunities.lock(user_id=user_id, id=opportunity_id)
    if opportunity.extraction_status is not ExtractionStatus.PENDING:
        return False
    values: dict[str, object] = {}
    filled: list[str] = []
    company_id = opportunity.company_id
    company_created = False
    if company_id is None:
        resolved = resolve_company(
            session, user_id=user_id, name=clean.company_name, domain=clean.company_domain
        )
        if resolved is not None:
            company, company_created = resolved
            company_id = company.id
            values["company_id"] = company_id
            filled.append("company_id")
    for name in ("title", "team", "location_text"):
        extracted = getattr(clean, name)
        if getattr(opportunity, name) is None and extracted is not None:
            values[name] = extracted
            filled.append(name)
    if opportunity.external_job_id is None and clean.external_job_id is not None:
        collides = company_id is not None and opportunities.external_job_id_taken(
            user_id=user_id,
            company_id=company_id,
            external_job_id=clean.external_job_id,
            exclude_id=opportunity.id,
        )
        if not collides:
            values["external_job_id"] = clean.external_job_id
            filled.append("external_job_id")
    if not opportunity.locations.get("items") and clean.locations.items:
        values["locations"] = clean.locations.model_dump(mode="json")
        filled.append("locations")
    if (
        opportunity.workplace_type is WorkplaceType.UNSPECIFIED
        and clean.workplace_type is not WorkplaceType.UNSPECIFIED
    ):
        values["workplace_type"] = clean.workplace_type
        filled.append("workplace_type")
    inserted = 0
    if (
        clean.qualifications
        and qualifications.count(user_id=user_id, opportunity_id=opportunity.id) == 0
    ):
        for ordinal, item in enumerate(clean.qualifications):
            session.add(
                Qualification(
                    user_id=user_id,
                    opportunity_id=opportunity.id,
                    kind=item.kind,
                    ordinal=ordinal,
                    text_verbatim=item.text_verbatim,
                    category=item.category,
                    skill_keys=item.skill_keys,
                    min_years=item.min_years,
                    is_hard_constraint=item.is_hard_constraint,
                    origin=QualificationOrigin.EXTRACTED,
                    llm_run_id=run_id,
                )
            )
        inserted = len(clean.qualifications)
        filled.append("qualifications")
    opportunities.update_fields(
        user_id=user_id,
        id=opportunity.id,
        values={
            **values,
            "extraction_status": ExtractionStatus.SUCCEEDED,
            "extraction_error_code": None,
            "llm_run_id": run_id,
        },
        content_changed=True,
    )
    record_event(
        session,
        user_id=user_id,
        aggregate_type=AggregateType.OPPORTUNITY,
        aggregate_id=opportunity_id,
        event_type=OPPORTUNITY_EXTRACTED,
        payload=OpportunityExtracted(
            opportunity_id=opportunity_id,
            llm_run_id=run_id,
            company_id=company_id,
            company_created=company_created,
            filled_fields=filled,
            qualification_count=inserted,
            dropped_qualification_count=clean.dropped_qualifications,
        ),
        actor=Actor.SYSTEM,
    )
    log.info(
        "jd_extracted",
        opportunity_id=str(opportunity_id),
        run_id=str(run_id),
        count=inserted,
        dropped_count=clean.dropped_qualifications,
    )
    return True


def make_extract_jd_handler(
    gateway: ModelGateway, settings: Settings
) -> Callable[[JobContext, ExtractJdPayload], None]:
    def handle(context: JobContext, payload: ExtractJdPayload) -> None:
        user_id = context.require_user_id()
        session = context.session
        try:
            opportunity: Opportunity = OpportunityRepository(session).get(
                user_id=user_id, id=payload.opportunity_id
            )
        except NotFound:
            log.info("extract_target_missing")
            return
        if opportunity.extraction_status is not ExtractionStatus.PENDING:
            log.info("extract_skipped", outcome=opportunity.extraction_status.value)
            return
        opportunity_id = opportunity.id
        artifact_id = opportunity.jd_artifact_id
        jd_text = OpportunityRepository(session).jd_text(user_id=user_id, artifact_id=artifact_id)
        if not jd_text:
            _mark_failed(
                session, user_id=user_id, opportunity_id=opportunity_id, code=JD_TEXT_MISSING
            )
            return
        session.commit()
        try:
            result = gateway.structured(
                user_id=user_id,
                purpose=LlmPurpose.EXTRACT_JD,
                prompt_id=JD_EXTRACT,
                tier=LlmTier.FAST,
                output_type=JdExtraction,
                variables={"jd": jd_text},
                context_manifest=[
                    ManifestEntry(entity_type="artifact", entity_id=artifact_id, version=0)
                ],
                max_output_tokens=settings.jd_extraction_max_output_tokens,
            )
        except LlmError as exc:
            _mark_failed(session, user_id=user_id, opportunity_id=opportunity_id, code=exc.code)
            return
        clean = clean_extraction(result.output, jd_text)
        apply_extraction(
            session,
            user_id=user_id,
            opportunity_id=opportunity_id,
            clean=clean,
            run_id=result.run_id,
        )

    return handle
