import uuid
from collections.abc import Mapping, Sequence
from typing import Any, cast

from sqlalchemy import Table, and_, delete, func, select, update

from app.db.models import (
    Artifact,
    ArtifactKind,
    Company,
    ExtractionStatus,
    Opportunity,
    OpportunityStatus,
    Priority,
    Qualification,
)
from app.db.tenancy import NotFound, UserScopedRepository, require_user_id
from app.db.versioning import update_versioned

DUPLICATE_CANDIDATE_LIMIT = 200
LIST_LIMIT = 200


class CompanyRepository(UserScopedRepository[Company]):
    model = Company

    def list_for_user(self, *, user_id: uuid.UUID) -> Sequence[Company]:
        return self.session.scalars(
            select(Company)
            .where(Company.user_id == require_user_id(user_id))
            .order_by(Company.normalized_name, Company.id)
        ).all()

    def find_by_domain(self, *, user_id: uuid.UUID, domain: str) -> Company | None:
        return self.session.scalars(
            select(Company)
            .where(Company.user_id == require_user_id(user_id), Company.domains.contains([domain]))
            .order_by(Company.created_at, Company.id)
            .limit(1)
        ).first()

    def find_by_normalized_name(self, *, user_id: uuid.UUID, normalized: str) -> Company | None:
        return self.session.scalars(
            select(Company).where(
                Company.user_id == require_user_id(user_id), Company.normalized_name == normalized
            )
        ).one_or_none()

    def with_aliases(self, *, user_id: uuid.UUID) -> Sequence[Company]:
        return self.session.scalars(
            select(Company)
            .where(
                Company.user_id == require_user_id(user_id),
                func.cardinality(Company.aliases) > 0,
            )
            .order_by(Company.created_at, Company.id)
        ).all()

    def name_taken(
        self, *, user_id: uuid.UUID, normalized: str, exclude_id: uuid.UUID | None = None
    ) -> bool:
        statement = select(Company.id).where(
            Company.user_id == require_user_id(user_id), Company.normalized_name == normalized
        )
        if exclude_id is not None:
            statement = statement.where(Company.id != exclude_id)
        return self.session.scalars(statement.limit(1)).first() is not None

    def opportunity_counts(
        self, *, user_id: uuid.UUID, company_id: uuid.UUID
    ) -> dict[OpportunityStatus, int]:
        rows = self.session.execute(
            select(Opportunity.status, func.count())
            .where(
                Opportunity.user_id == require_user_id(user_id),
                Opportunity.company_id == company_id,
            )
            .group_by(Opportunity.status)
        ).all()
        counts = dict.fromkeys(OpportunityStatus, 0)
        for status, count in rows:
            counts[status] = count
        return counts


class OpportunityRepository(UserScopedRepository[Opportunity]):
    model = Opportunity

    def list_with_companies(
        self,
        *,
        user_id: uuid.UUID,
        status: OpportunityStatus | None = None,
        priority: Priority | None = None,
        company_id: uuid.UUID | None = None,
    ) -> Sequence[tuple[Opportunity, Company | None]]:
        statement = (
            select(Opportunity, Company)
            .outerjoin(
                Company,
                and_(Company.user_id == Opportunity.user_id, Company.id == Opportunity.company_id),
            )
            .where(Opportunity.user_id == require_user_id(user_id))
            .order_by(Opportunity.discovered_at.desc(), Opportunity.id.desc())
            .limit(LIST_LIMIT)
        )
        if status is not None:
            statement = statement.where(Opportunity.status == status)
        if priority is not None:
            statement = statement.where(Opportunity.priority == priority)
        if company_id is not None:
            statement = statement.where(Opportunity.company_id == company_id)
        return [(row, company) for row, company in self.session.execute(statement)]

    def get_with_company(
        self, *, user_id: uuid.UUID, id: uuid.UUID
    ) -> tuple[Opportunity, Company | None]:
        row = self.session.execute(
            select(Opportunity, Company)
            .outerjoin(
                Company,
                and_(Company.user_id == Opportunity.user_id, Company.id == Opportunity.company_id),
            )
            .where(Opportunity.user_id == require_user_id(user_id), Opportunity.id == id)
        ).one_or_none()
        if row is None:
            raise NotFound("Opportunity")
        return row[0], row[1]

    def find_by_artifact(self, *, user_id: uuid.UUID, artifact_id: uuid.UUID) -> Opportunity | None:
        return self.session.scalars(
            select(Opportunity).where(
                Opportunity.user_id == require_user_id(user_id),
                Opportunity.jd_artifact_id == artifact_id,
            )
        ).one_or_none()

    def find_by_jd_hash(self, *, user_id: uuid.UUID, sha256: bytes) -> Opportunity | None:
        return self.session.scalars(
            select(Opportunity)
            .join(
                Artifact,
                and_(
                    Artifact.user_id == Opportunity.user_id,
                    Artifact.id == Opportunity.jd_artifact_id,
                ),
            )
            .where(
                Opportunity.user_id == require_user_id(user_id),
                Artifact.kind == ArtifactKind.JD_SNAPSHOT,
                Artifact.sha256 == sha256,
            )
        ).one_or_none()

    def jd_text(self, *, user_id: uuid.UUID, artifact_id: uuid.UUID) -> str | None:
        return self.session.scalars(
            select(Artifact.extracted_text).where(
                Artifact.user_id == require_user_id(user_id), Artifact.id == artifact_id
            )
        ).one_or_none()

    def lock(self, *, user_id: uuid.UUID, id: uuid.UUID) -> Opportunity:
        row = self.session.scalars(
            select(Opportunity)
            .where(Opportunity.user_id == require_user_id(user_id), Opportunity.id == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one_or_none()
        if row is None:
            raise NotFound("Opportunity")
        return row

    def external_job_id_taken(
        self,
        *,
        user_id: uuid.UUID,
        company_id: uuid.UUID,
        external_job_id: str,
        exclude_id: uuid.UUID,
    ) -> bool:
        return (
            self.session.scalars(
                select(Opportunity.id)
                .where(
                    Opportunity.user_id == require_user_id(user_id),
                    Opportunity.company_id == company_id,
                    Opportunity.external_job_id == external_job_id,
                    Opportunity.id != exclude_id,
                )
                .limit(1)
            ).first()
            is not None
        )

    def duplicate_candidates(
        self, *, user_id: uuid.UUID, company_id: uuid.UUID, exclude_id: uuid.UUID
    ) -> Sequence[tuple[Opportunity, Company | None]]:
        statement = (
            select(Opportunity, Company)
            .outerjoin(
                Company,
                and_(Company.user_id == Opportunity.user_id, Company.id == Opportunity.company_id),
            )
            .where(
                Opportunity.user_id == require_user_id(user_id),
                Opportunity.company_id == company_id,
                Opportunity.id != exclude_id,
            )
            .order_by(Opportunity.discovered_at.desc(), Opportunity.id.desc())
            .limit(DUPLICATE_CANDIDATE_LIMIT)
        )
        return [(row, company) for row, company in self.session.execute(statement)]

    def update_fields(
        self,
        *,
        user_id: uuid.UUID,
        id: uuid.UUID,
        values: Mapping[str, Any],
        expected_version: int | None = None,
        content_changed: bool = False,
    ) -> int:
        changes: dict[str, Any] = {**values, "updated_at": func.now()}
        if content_changed:
            changes["content_updated_at"] = func.now()
        self.session.flush()
        table = cast(Table, Opportunity.__table__)
        if expected_version is not None:
            version = update_versioned(
                self.session,
                table,
                user_id=user_id,
                id=id,
                expected_version=expected_version,
                values=changes,
            )
        else:
            version = self.session.execute(
                update(table)
                .where(table.c.id == id, table.c.user_id == require_user_id(user_id))
                .values(**changes, state_version=table.c.state_version + 1)
                .returning(table.c.state_version)
            ).scalar_one()
        self.session.expire_all()
        return int(version)

    def mark_failed(self, *, user_id: uuid.UUID, id: uuid.UUID, error_code: str) -> None:
        self.update_fields(
            user_id=user_id,
            id=id,
            values={
                "extraction_status": ExtractionStatus.FAILED.value,
                "extraction_error_code": error_code,
            },
        )


class QualificationRepository(UserScopedRepository[Qualification]):
    model = Qualification

    def list_for_opportunity(
        self, *, user_id: uuid.UUID, opportunity_id: uuid.UUID
    ) -> Sequence[Qualification]:
        return self.session.scalars(
            select(Qualification)
            .where(
                Qualification.user_id == require_user_id(user_id),
                Qualification.opportunity_id == opportunity_id,
            )
            .order_by(Qualification.ordinal, Qualification.created_at, Qualification.id)
        ).all()

    def count(self, *, user_id: uuid.UUID, opportunity_id: uuid.UUID) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(Qualification)
                .where(
                    Qualification.user_id == require_user_id(user_id),
                    Qualification.opportunity_id == opportunity_id,
                )
            )
            or 0
        )

    def next_ordinal(self, *, user_id: uuid.UUID, opportunity_id: uuid.UUID) -> int:
        highest = self.session.scalar(
            select(func.max(Qualification.ordinal)).where(
                Qualification.user_id == require_user_id(user_id),
                Qualification.opportunity_id == opportunity_id,
            )
        )
        return 0 if highest is None else int(highest) + 1

    def delete_row(self, *, user_id: uuid.UUID, id: uuid.UUID) -> None:
        self.session.execute(
            delete(Qualification).where(
                Qualification.user_id == require_user_id(user_id), Qualification.id == id
            )
        )
