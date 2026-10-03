import hashlib
import io
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.artifacts.storage import StorageAdapter, artifact_key
from app.config import Settings
from app.core.errors import ApiError
from app.core.ids import new_id
from app.db.models import (
    Actor,
    AggregateType,
    Artifact,
    ArtifactKind,
    Company,
    ExtractionStatus,
    Opportunity,
    OpportunitySource,
    OpportunityStatus,
    Priority,
    Qualification,
    QualificationOrigin,
    WorkplaceType,
)
from app.db.tenancy import resolve_owned
from app.db.versioning import ConcurrencyConflict
from app.jobs.queue import enqueue
from app.opportunities.duplicates import duplicate_reason
from app.opportunities.events import (
    OPPORTUNITY_CONTENT_EDITED,
    OPPORTUNITY_INGESTED,
    OPPORTUNITY_PRIORITY_CHANGED,
    OpportunityContentEdited,
    OpportunityIngested,
    OpportunityPriorityChanged,
    record_event,
)
from app.opportunities.jobs import EXTRACT_JD_JOB, ExtractJdPayload, extract_unique_key
from app.opportunities.repository import (
    CompanyRepository,
    OpportunityRepository,
    QualificationRepository,
)
from app.opportunities.schemas import (
    DuplicateMatch,
    Locations,
    OpportunityPatch,
    OpportunitySummary,
    QualificationCreate,
    QualificationPatch,
)

JD_MIME_TYPE = "text/plain; charset=utf-8"
JD_FILENAME = "job-description.txt"
PATCHABLE_FIELDS = (
    "title",
    "team",
    "external_job_id",
    "location_text",
    "locations",
    "workplace_type",
    "company_id",
    "source_url",
)
QUALIFICATION_PATCHABLE_FIELDS = (
    "kind",
    "category",
    "skill_keys",
    "min_years",
    "is_hard_constraint",
    "ordinal",
)


def normalize_jd_text(raw: str) -> str:
    return raw.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "").strip()


class OpportunityService:
    def __init__(self, session: Session, storage: StorageAdapter, settings: Settings) -> None:
        self.session = session
        self.storage = storage
        self.settings = settings
        self.opportunities = OpportunityRepository(session)
        self.companies = CompanyRepository(session)
        self.qualifications = QualificationRepository(session)

    def ingest(
        self, *, user_id: uuid.UUID, jd_text: str, source_url: str | None
    ) -> OpportunitySummary:
        text = normalize_jd_text(jd_text)
        if len(text) < self.settings.jd_min_chars:
            raise ApiError(422, "jd_too_short")
        if len(text) > self.settings.jd_max_chars:
            raise ApiError(422, "jd_too_long")
        data = text.encode("utf-8")
        digest = hashlib.sha256(data).digest()
        self._reject_duplicate(user_id=user_id, digest=digest)
        artifact_id = new_id()
        key = artifact_key(user_id, artifact_id)
        self.storage.put(key, io.BytesIO(data))
        try:
            self.session.add(
                Artifact(
                    id=artifact_id,
                    user_id=user_id,
                    kind=ArtifactKind.JD_SNAPSHOT,
                    storage_key=key,
                    sha256=digest,
                    mime_type=JD_MIME_TYPE,
                    byte_size=len(data),
                    original_filename=JD_FILENAME,
                    extracted_text=text,
                    extraction_status=ExtractionStatus.SUCCEEDED,
                )
            )
            self.session.flush()
            now = datetime.now(UTC)
            opportunity = Opportunity(
                user_id=user_id,
                jd_artifact_id=artifact_id,
                source=OpportunitySource.MANUAL_PASTE,
                source_url=source_url,
                locations=Locations().model_dump(mode="json"),
                workplace_type=WorkplaceType.UNSPECIFIED,
                status=OpportunityStatus.NEW,
                priority=Priority.NORMAL,
                extraction_status=ExtractionStatus.PENDING,
                content_updated_at=now,
                discovered_at=now,
            )
            self.session.add(opportunity)
            self.session.flush()
            record_event(
                self.session,
                user_id=user_id,
                aggregate_type=AggregateType.OPPORTUNITY,
                aggregate_id=opportunity.id,
                event_type=OPPORTUNITY_INGESTED,
                payload=OpportunityIngested(
                    opportunity_id=opportunity.id,
                    artifact_id=artifact_id,
                    has_source_url=source_url is not None,
                ),
                actor=Actor.USER,
            )
            enqueue(
                self.session,
                kind=EXTRACT_JD_JOB,
                payload=ExtractJdPayload(opportunity_id=opportunity.id),
                user_id=user_id,
                unique_key=extract_unique_key(opportunity.id),
            )
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            self.storage.delete_prefix(key)
            self._reject_duplicate(user_id=user_id, digest=digest)
            raise
        except BaseException:
            self.session.rollback()
            self.storage.delete_prefix(key)
            raise
        return OpportunitySummary.build(opportunity, None)

    def _reject_duplicate(self, *, user_id: uuid.UUID, digest: bytes) -> None:
        existing = self.opportunities.find_by_jd_hash(user_id=user_id, sha256=digest)
        if existing is not None:
            raise ApiError(409, "duplicate_jd", opportunity_id=existing.id)

    def list_summaries(
        self,
        *,
        user_id: uuid.UUID,
        status: OpportunityStatus | None,
        priority: Priority | None,
        company_id: uuid.UUID | None,
    ) -> list[OpportunitySummary]:
        rows = self.opportunities.list_with_companies(
            user_id=user_id, status=status, priority=priority, company_id=company_id
        )
        return [OpportunitySummary.build(row, company) for row, company in rows]

    def get_detail(
        self, *, user_id: uuid.UUID, opportunity_id: uuid.UUID
    ) -> tuple[Opportunity, Company | None, str, Sequence[Qualification]]:
        row, company = self.opportunities.get_with_company(user_id=user_id, id=opportunity_id)
        jd_text = self.opportunities.jd_text(user_id=user_id, artifact_id=row.jd_artifact_id)
        qualifications = self.qualifications.list_for_opportunity(
            user_id=user_id, opportunity_id=row.id
        )
        return row, company, jd_text or "", qualifications

    def patch(
        self, *, user_id: uuid.UUID, opportunity_id: uuid.UUID, data: OpportunityPatch
    ) -> None:
        row = self.opportunities.lock(user_id=user_id, id=opportunity_id)
        if data.expected_state_version != row.state_version:
            raise ApiError(409, "conflict")
        changes = self._content_changes(row, data, user_id=user_id)
        if not changes:
            self.session.rollback()
            return
        try:
            self.opportunities.update_fields(
                user_id=user_id,
                id=row.id,
                values=changes,
                expected_version=data.expected_state_version,
                content_changed=True,
            )
        except ConcurrencyConflict as exc:
            self.session.rollback()
            raise ApiError(409, "conflict") from exc
        except IntegrityError as exc:
            self.session.rollback()
            raise ApiError(409, "duplicate_job_id") from exc
        self._record_content_edit(user_id=user_id, opportunity_id=row.id, fields=sorted(changes))
        self.session.commit()

    def _content_changes(
        self, row: Opportunity, data: OpportunityPatch, *, user_id: uuid.UUID
    ) -> dict[str, Any]:
        changes: dict[str, Any] = {}
        for name in PATCHABLE_FIELDS:
            if name not in data.model_fields_set:
                continue
            new: Any = getattr(data, name)
            if name == "locations":
                new = new.model_dump(mode="json")
            if new != getattr(row, name):
                changes[name] = new
        company_id = changes.get("company_id")
        if company_id is not None:
            resolve_owned(self.session, Company, user_id=user_id, id=company_id)
        return changes

    def set_priority(
        self, *, user_id: uuid.UUID, opportunity_id: uuid.UUID, priority: Priority
    ) -> None:
        row = self.opportunities.lock(user_id=user_id, id=opportunity_id)
        previous = row.priority
        if previous is priority:
            self.session.rollback()
            return
        self.opportunities.update_fields(user_id=user_id, id=row.id, values={"priority": priority})
        record_event(
            self.session,
            user_id=user_id,
            aggregate_type=AggregateType.OPPORTUNITY,
            aggregate_id=row.id,
            event_type=OPPORTUNITY_PRIORITY_CHANGED,
            payload=OpportunityPriorityChanged(
                opportunity_id=row.id,
                from_priority=previous.value,
                to_priority=priority.value,
            ),
            actor=Actor.USER,
        )
        self.session.commit()

    def request_extraction(self, *, user_id: uuid.UUID, opportunity_id: uuid.UUID) -> None:
        row = self.opportunities.lock(user_id=user_id, id=opportunity_id)
        if row.extraction_status is not ExtractionStatus.FAILED:
            self.session.rollback()
            raise ApiError(409, "invalid_state")
        self.opportunities.update_fields(
            user_id=user_id,
            id=row.id,
            values={
                "extraction_status": ExtractionStatus.PENDING,
                "extraction_error_code": None,
            },
        )
        enqueue(
            self.session,
            kind=EXTRACT_JD_JOB,
            payload=ExtractJdPayload(opportunity_id=row.id),
            user_id=user_id,
            unique_key=extract_unique_key(row.id),
        )
        self.session.commit()

    def duplicates(self, *, user_id: uuid.UUID, opportunity_id: uuid.UUID) -> list[DuplicateMatch]:
        subject, _ = self.opportunities.get_with_company(user_id=user_id, id=opportunity_id)
        if subject.company_id is None:
            return []
        matches: list[DuplicateMatch] = []
        for candidate, company in self.opportunities.duplicate_candidates(
            user_id=user_id, company_id=subject.company_id, exclude_id=subject.id
        ):
            found = duplicate_reason(subject, candidate)
            if found is not None:
                reason, similarity = found
                matches.append(
                    DuplicateMatch(
                        opportunity=OpportunitySummary.build(candidate, company),
                        reason=reason,
                        similarity=similarity,
                    )
                )
        matches.sort(key=lambda match: (match.reason != "exact_job_id", -match.similarity))
        return matches

    def add_qualification(
        self, *, user_id: uuid.UUID, opportunity_id: uuid.UUID, data: QualificationCreate
    ) -> Qualification:
        parent = self.opportunities.lock(user_id=user_id, id=opportunity_id)
        ordinal = (
            data.ordinal
            if data.ordinal is not None
            else self.qualifications.next_ordinal(user_id=user_id, opportunity_id=parent.id)
        )
        row = Qualification(
            user_id=user_id,
            opportunity_id=parent.id,
            kind=data.kind,
            ordinal=ordinal,
            text_verbatim=data.text_verbatim,
            category=data.category,
            skill_keys=data.skill_keys,
            min_years=data.min_years,
            is_hard_constraint=data.is_hard_constraint,
            origin=QualificationOrigin.USER,
        )
        self.session.add(row)
        self._touch_parent(user_id=user_id, parent_id=parent.id)
        self.session.commit()
        self.session.refresh(row)
        return row

    def update_qualification(
        self, *, user_id: uuid.UUID, qualification_id: uuid.UUID, data: QualificationPatch
    ) -> Qualification:
        row = self.qualifications.get(user_id=user_id, id=qualification_id)
        parent = self.opportunities.lock(user_id=user_id, id=row.opportunity_id)
        changed = False
        for name in QUALIFICATION_PATCHABLE_FIELDS:
            if name in data.model_fields_set and getattr(data, name) != getattr(row, name):
                setattr(row, name, getattr(data, name))
                changed = True
        if changed:
            self._touch_parent(user_id=user_id, parent_id=parent.id)
        self.session.commit()
        self.session.refresh(row)
        return row

    def delete_qualification(self, *, user_id: uuid.UUID, qualification_id: uuid.UUID) -> None:
        row = self.qualifications.get(user_id=user_id, id=qualification_id)
        parent = self.opportunities.lock(user_id=user_id, id=row.opportunity_id)
        self.qualifications.delete_row(user_id=user_id, id=row.id)
        self._touch_parent(user_id=user_id, parent_id=parent.id)
        self.session.commit()

    def _touch_parent(self, *, user_id: uuid.UUID, parent_id: uuid.UUID) -> None:
        self.opportunities.update_fields(
            user_id=user_id, id=parent_id, values={}, content_changed=True
        )
        self._record_content_edit(
            user_id=user_id, opportunity_id=parent_id, fields=["qualifications"]
        )

    def _record_content_edit(
        self, *, user_id: uuid.UUID, opportunity_id: uuid.UUID, fields: list[str]
    ) -> None:
        record_event(
            self.session,
            user_id=user_id,
            aggregate_type=AggregateType.OPPORTUNITY,
            aggregate_id=opportunity_id,
            event_type=OPPORTUNITY_CONTENT_EDITED,
            payload=OpportunityContentEdited(opportunity_id=opportunity_id, fields=fields),
            actor=Actor.USER,
        )
