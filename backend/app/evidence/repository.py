import uuid
from collections.abc import Collection, Sequence

from sqlalchemy import and_, delete, exists, func, select, text, update
from sqlalchemy.orm import Session

from app.db.models import (
    Claim,
    ClaimSkill,
    ConfirmationStatus,
    EvidenceClass,
    EvidenceSource,
    EvidenceSourceType,
    Resume,
    Skill,
)
from app.db.tenancy import NotFound, UserScopedRepository, require_user_id
from app.evidence.assessment import BLOCKS_GAP, ClaimFacts

LIST_LIMIT = 500


def lock_row[M: (Skill, Claim)](
    session: Session, model: type[M], *, user_id: uuid.UUID, id: uuid.UUID
) -> M:
    row = session.scalars(
        select(model)
        .where(model.user_id == require_user_id(user_id), model.id == id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one_or_none()
    if row is None:
        raise NotFound(model.__name__)
    return row


class SkillRepository(UserScopedRepository[Skill]):
    model = Skill

    def lock_names(self, *, user_id: uuid.UUID) -> None:
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"skill-names:{require_user_id(user_id)}"},
        )

    def active_for_user(self, *, user_id: uuid.UUID) -> Sequence[Skill]:
        return self.session.scalars(
            select(Skill)
            .where(Skill.user_id == require_user_id(user_id), Skill.merged_into_skill_id.is_(None))
            .order_by(Skill.canonical_name, Skill.id)
            .limit(LIST_LIMIT)
        ).all()

    def all_for_user(self, *, user_id: uuid.UUID) -> Sequence[Skill]:
        return self.session.scalars(
            select(Skill)
            .where(Skill.user_id == require_user_id(user_id))
            .order_by(Skill.canonical_name, Skill.id)
            .limit(LIST_LIMIT)
        ).all()

    def touch(self, *, user_id: uuid.UUID, skill_ids: Collection[uuid.UUID]) -> None:
        if not skill_ids:
            return
        self.session.execute(
            update(Skill)
            .where(Skill.user_id == require_user_id(user_id), Skill.id.in_(list(skill_ids)))
            .values(updated_at=func.now())
            .execution_options(synchronize_session=False)
        )

    def has_gap_blocking_evidence(self, *, user_id: uuid.UUID, skill_id: uuid.UUID) -> bool:
        return bool(
            self.session.scalar(
                select(
                    exists().where(
                        ClaimSkill.user_id == require_user_id(user_id),
                        ClaimSkill.skill_id == skill_id,
                        Claim.user_id == ClaimSkill.user_id,
                        Claim.id == ClaimSkill.claim_id,
                        Claim.confirmation_status == ConfirmationStatus.CONFIRMED,
                        Claim.evidence_class.in_(BLOCKS_GAP),
                    )
                )
            )
        )

    def claim_facts(
        self, *, user_id: uuid.UUID, skill_ids: Collection[uuid.UUID]
    ) -> dict[uuid.UUID, list[ClaimFacts]]:
        facts: dict[uuid.UUID, list[ClaimFacts]] = {skill_id: [] for skill_id in skill_ids}
        if not skill_ids:
            return facts
        rows = self.session.execute(
            select(
                ClaimSkill.skill_id,
                Claim.evidence_class,
                Claim.engagement_type,
                Claim.confirmation_status,
                Claim.start_date,
                Claim.end_date,
            )
            .join(Claim, and_(Claim.user_id == ClaimSkill.user_id, Claim.id == ClaimSkill.claim_id))
            .where(
                ClaimSkill.user_id == require_user_id(user_id),
                ClaimSkill.skill_id.in_(list(skill_ids)),
            )
        )
        for skill_id, evidence_class, engagement_type, status, start, end in rows:
            facts[skill_id].append(ClaimFacts(evidence_class, engagement_type, status, start, end))
        return facts

    def stated_resume_ids(
        self, *, user_id: uuid.UUID, skill_ids: Collection[uuid.UUID]
    ) -> set[tuple[uuid.UUID, uuid.UUID]]:
        if not skill_ids:
            return set()
        rows = self.session.execute(
            select(ClaimSkill.skill_id, Resume.id)
            .join(Claim, and_(Claim.user_id == ClaimSkill.user_id, Claim.id == ClaimSkill.claim_id))
            .join(
                EvidenceSource,
                and_(EvidenceSource.user_id == Claim.user_id, EvidenceSource.claim_id == Claim.id),
            )
            .join(
                Resume,
                and_(
                    Resume.user_id == EvidenceSource.user_id,
                    Resume.artifact_id == EvidenceSource.artifact_id,
                ),
            )
            .where(
                ClaimSkill.user_id == require_user_id(user_id),
                ClaimSkill.skill_id.in_(list(skill_ids)),
                Claim.confirmation_status != ConfirmationStatus.REJECTED,
                EvidenceSource.source_type == EvidenceSourceType.RESUME,
            )
        )
        return {(skill_id, resume_id) for skill_id, resume_id in rows}

    def mentioned_resume_ids(
        self, *, user_id: uuid.UUID, skill_ids: Collection[uuid.UUID]
    ) -> set[tuple[uuid.UUID, uuid.UUID]]:
        if not skill_ids:
            return set()
        rows = self.session.execute(
            text(
                "WITH docs AS ("
                " SELECT r.id AS resume_id,"
                " to_tsvector('simple', coalesce(a.extracted_text, '')) AS doc"
                " FROM resumes r JOIN artifacts a ON a.user_id = r.user_id AND a.id = r.artifact_id"
                " WHERE r.user_id = :user_id),"
                " terms AS ("
                " SELECT s.id AS skill_id, t.term"
                " FROM skills s"
                " CROSS JOIN LATERAL unnest(array_append(s.aliases, s.canonical_name)) AS t(term)"
                " WHERE s.user_id = :user_id AND s.id = ANY(:skill_ids))"
                " SELECT DISTINCT terms.skill_id, docs.resume_id FROM terms"
                " JOIN docs ON docs.doc @@ phraseto_tsquery('simple', terms.term)"
            ),
            {"user_id": require_user_id(user_id), "skill_ids": list(skill_ids)},
        )
        return {(skill_id, resume_id) for skill_id, resume_id in rows}

    def resume_labels(
        self, *, user_id: uuid.UUID, resume_ids: Collection[uuid.UUID]
    ) -> dict[uuid.UUID, Resume]:
        if not resume_ids:
            return {}
        rows = self.session.scalars(
            select(Resume).where(
                Resume.user_id == require_user_id(user_id), Resume.id.in_(list(resume_ids))
            )
        )
        return {resume.id: resume for resume in rows}


class ClaimRepository(UserScopedRepository[Claim]):
    model = Claim

    def list_filtered(
        self,
        *,
        user_id: uuid.UUID,
        status: ConfirmationStatus | None,
        evidence_class: EvidenceClass | None,
        skill_id: uuid.UUID | None,
        resume_id: uuid.UUID | None,
    ) -> Sequence[Claim]:
        statement = select(Claim).where(Claim.user_id == require_user_id(user_id))
        if status is not None:
            statement = statement.where(Claim.confirmation_status == status)
        if evidence_class is not None:
            statement = statement.where(Claim.evidence_class == evidence_class)
        if skill_id is not None:
            statement = statement.where(
                exists().where(
                    ClaimSkill.user_id == Claim.user_id,
                    ClaimSkill.claim_id == Claim.id,
                    ClaimSkill.skill_id == skill_id,
                )
            )
        if resume_id is not None:
            statement = statement.where(
                exists().where(
                    EvidenceSource.user_id == Claim.user_id,
                    EvidenceSource.claim_id == Claim.id,
                    EvidenceSource.source_type == EvidenceSourceType.RESUME,
                    Resume.user_id == EvidenceSource.user_id,
                    Resume.artifact_id == EvidenceSource.artifact_id,
                    Resume.id == resume_id,
                )
            )
        return self.session.scalars(
            statement.order_by(Claim.created_at.desc(), Claim.id.desc()).limit(LIST_LIMIT)
        ).all()

    def for_skill(self, *, user_id: uuid.UUID, skill_id: uuid.UUID) -> Sequence[Claim]:
        return self.session.scalars(
            select(Claim)
            .join(
                ClaimSkill,
                and_(ClaimSkill.user_id == Claim.user_id, ClaimSkill.claim_id == Claim.id),
            )
            .where(ClaimSkill.user_id == require_user_id(user_id), ClaimSkill.skill_id == skill_id)
            .order_by(Claim.created_at.desc(), Claim.id.desc())
        ).all()

    def sources_for(
        self, *, user_id: uuid.UUID, claim_ids: Collection[uuid.UUID]
    ) -> dict[uuid.UUID, list[EvidenceSource]]:
        grouped: dict[uuid.UUID, list[EvidenceSource]] = {claim_id: [] for claim_id in claim_ids}
        if not claim_ids:
            return grouped
        for source in self.session.scalars(
            select(EvidenceSource)
            .where(
                EvidenceSource.user_id == require_user_id(user_id),
                EvidenceSource.claim_id.in_(list(claim_ids)),
            )
            .order_by(EvidenceSource.created_at, EvidenceSource.id)
        ):
            grouped[source.claim_id].append(source)
        return grouped

    def skills_for(
        self, *, user_id: uuid.UUID, claim_ids: Collection[uuid.UUID]
    ) -> dict[uuid.UUID, list[Skill]]:
        grouped: dict[uuid.UUID, list[Skill]] = {claim_id: [] for claim_id in claim_ids}
        if not claim_ids:
            return grouped
        rows = self.session.execute(
            select(ClaimSkill.claim_id, Skill)
            .join(Skill, and_(Skill.user_id == ClaimSkill.user_id, Skill.id == ClaimSkill.skill_id))
            .where(
                ClaimSkill.user_id == require_user_id(user_id),
                ClaimSkill.claim_id.in_(list(claim_ids)),
            )
            .order_by(Skill.canonical_name, Skill.id)
        )
        for claim_id, skill in rows:
            grouped[claim_id].append(skill)
        return grouped

    def linked_skill_ids(self, *, user_id: uuid.UUID, claim_id: uuid.UUID) -> list[uuid.UUID]:
        return list(
            self.session.scalars(
                select(ClaimSkill.skill_id).where(
                    ClaimSkill.user_id == require_user_id(user_id), ClaimSkill.claim_id == claim_id
                )
            )
        )

    def find_link(
        self, *, user_id: uuid.UUID, claim_id: uuid.UUID, skill_id: uuid.UUID
    ) -> ClaimSkill | None:
        return self.session.scalars(
            select(ClaimSkill).where(
                ClaimSkill.user_id == require_user_id(user_id),
                ClaimSkill.claim_id == claim_id,
                ClaimSkill.skill_id == skill_id,
            )
        ).one_or_none()

    def delete_links(self, *, user_id: uuid.UUID, link_ids: Collection[uuid.UUID]) -> None:
        if link_ids:
            self.session.execute(
                delete(ClaimSkill).where(
                    ClaimSkill.user_id == require_user_id(user_id),
                    ClaimSkill.id.in_(list(link_ids)),
                )
            )

    def links_for_skill(self, *, user_id: uuid.UUID, skill_id: uuid.UUID) -> Sequence[ClaimSkill]:
        return self.session.scalars(
            select(ClaimSkill).where(
                ClaimSkill.user_id == require_user_id(user_id), ClaimSkill.skill_id == skill_id
            )
        ).all()
