import uuid
from collections.abc import Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.models import Actor, AggregateType, Company, CompanyOrigin, OpportunityStatus
from app.opportunities.events import (
    COMPANY_CREATED,
    COMPANY_PRIORITY_CHANGED,
    CompanyCreated,
    CompanyPriorityChanged,
    record_event,
)
from app.opportunities.normalize import (
    collapse_whitespace,
    normalize_company_name,
    normalize_domain,
)
from app.opportunities.repository import CompanyRepository
from app.opportunities.schemas import CompanyCreate, CompanyPatch

MAX_NAME_CHARS = 200


def resolve_company(
    session: Session, *, user_id: uuid.UUID, name: str | None, domain: str | None
) -> tuple[Company, bool] | None:
    companies = CompanyRepository(session)
    cleaned_domain = normalize_domain(domain) if domain else None
    if cleaned_domain is not None:
        by_domain = companies.find_by_domain(user_id=user_id, domain=cleaned_domain)
        if by_domain is not None:
            return by_domain, False
    display = collapse_whitespace(name or "")[:MAX_NAME_CHARS]
    normalized = normalize_company_name(display)
    if not normalized:
        return None
    by_name = companies.find_by_normalized_name(user_id=user_id, normalized=normalized)
    if by_name is not None:
        return by_name, False
    for candidate in companies.with_aliases(user_id=user_id):
        if normalized in {normalize_company_name(alias) for alias in candidate.aliases}:
            return candidate, False
    company = Company(
        user_id=user_id,
        name=display,
        normalized_name=normalized,
        aliases=[],
        domains=[] if cleaned_domain is None else [cleaned_domain],
        notes="",
        origin=CompanyOrigin.EXTRACTED,
    )
    try:
        with session.begin_nested():
            session.add(company)
            session.flush()
    except IntegrityError:
        existing = companies.find_by_normalized_name(user_id=user_id, normalized=normalized)
        if existing is None:
            raise
        return existing, False
    record_event(
        session,
        user_id=user_id,
        aggregate_type=AggregateType.COMPANY,
        aggregate_id=company.id,
        event_type=COMPANY_CREATED,
        payload=CompanyCreated(company_id=company.id, origin=CompanyOrigin.EXTRACTED.value),
        actor=Actor.SYSTEM,
    )
    return company, True


class CompanyService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.companies = CompanyRepository(session)

    def list(self, *, user_id: uuid.UUID) -> Sequence[Company]:
        return self.companies.list_for_user(user_id=user_id)

    def get_detail(
        self, *, user_id: uuid.UUID, company_id: uuid.UUID
    ) -> tuple[Company, dict[OpportunityStatus, int]]:
        company = self.companies.get(user_id=user_id, id=company_id)
        counts = self.companies.opportunity_counts(user_id=user_id, company_id=company.id)
        return company, counts

    def create(self, *, user_id: uuid.UUID, data: CompanyCreate) -> Company:
        normalized = normalize_company_name(data.name)
        if not normalized:
            raise ApiError(422, "invalid_name")
        if self.companies.name_taken(user_id=user_id, normalized=normalized):
            raise ApiError(409, "company_name_taken")
        company = Company(
            user_id=user_id,
            name=data.name,
            normalized_name=normalized,
            aliases=data.aliases,
            domains=data.domains,
            careers_url=data.careers_url,
            strategic_priority=data.strategic_priority,
            notes=data.notes,
            origin=CompanyOrigin.USER,
        )
        self.session.add(company)
        try:
            self.session.flush()
            record_event(
                self.session,
                user_id=user_id,
                aggregate_type=AggregateType.COMPANY,
                aggregate_id=company.id,
                event_type=COMPANY_CREATED,
                payload=CompanyCreated(company_id=company.id, origin=CompanyOrigin.USER.value),
                actor=Actor.USER,
            )
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ApiError(409, "company_name_taken") from exc
        self.session.refresh(company)
        return company

    def patch(self, *, user_id: uuid.UUID, company_id: uuid.UUID, data: CompanyPatch) -> Company:
        company = self.companies.get(user_id=user_id, id=company_id)
        fields = data.model_fields_set
        previous_priority = company.strategic_priority
        if "name" in fields and data.name is not None and data.name != company.name:
            normalized = normalize_company_name(data.name)
            if not normalized:
                raise ApiError(422, "invalid_name")
            if self.companies.name_taken(
                user_id=user_id, normalized=normalized, exclude_id=company.id
            ):
                raise ApiError(409, "company_name_taken")
            company.name = data.name
            company.normalized_name = normalized
        if "aliases" in fields and data.aliases is not None:
            company.aliases = data.aliases
        if "domains" in fields and data.domains is not None:
            company.domains = data.domains
        if "careers_url" in fields:
            company.careers_url = data.careers_url
        if "notes" in fields and data.notes is not None:
            company.notes = data.notes
        if "strategic_priority" in fields and data.strategic_priority is not None:
            company.strategic_priority = data.strategic_priority
        try:
            self.session.flush()
            if company.strategic_priority is not previous_priority:
                record_event(
                    self.session,
                    user_id=user_id,
                    aggregate_type=AggregateType.COMPANY,
                    aggregate_id=company.id,
                    event_type=COMPANY_PRIORITY_CHANGED,
                    payload=CompanyPriorityChanged(
                        company_id=company.id,
                        from_priority=previous_priority.value,
                        to_priority=company.strategic_priority.value,
                    ),
                    actor=Actor.USER,
                )
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ApiError(409, "company_name_taken") from exc
        self.session.refresh(company)
        return company
