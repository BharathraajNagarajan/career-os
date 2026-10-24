import uuid
from collections.abc import Callable, Collection, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.applications.service import run_in_transaction
from app.db.models import (
    Claim,
    ConfirmationStatus,
    EngagementType,
    EvidenceClass,
    EvidenceOrigin,
    EvidenceSource,
    Resume,
    ResumeStatus,
    Skill,
)
from app.db.tenancy import resolve_owned
from app.evidence import commands
from app.evidence.assessment import Assessment, Category, assess
from app.evidence.commands import SourceInput
from app.evidence.repository import ClaimRepository, SkillRepository
from app.evidence.schemas import (
    BadgeResponse,
    ClaimCreate,
    ClaimResponse,
    HeadlineResponse,
    ResumeExposure,
    SkillDetail,
    SkillRef,
    SkillSummary,
    SourceCreate,
    SourceResponse,
)


def source_input(body: SourceCreate) -> SourceInput:
    return SourceInput(
        source_type=body.source_type,
        resume_id=body.resume_id,
        artifact_id=body.artifact_id,
        url=body.url,
        assertion_text=body.assertion_text,
        locator=body.locator,
    )


class EvidenceService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.skills = SkillRepository(session)
        self.claims = ClaimRepository(session)

    def _commit[R](self, work: Callable[[], R]) -> R:
        return run_in_transaction(self.session, work, commit=True)

    def list_skills(
        self,
        *,
        user_id: uuid.UUID,
        query: str | None,
        category: Category | None,
        engagement: EngagementType | None,
        status: ConfirmationStatus | None,
        include_merged: bool,
    ) -> list[SkillSummary]:
        rows = (
            self.skills.all_for_user(user_id=user_id)
            if include_merged
            else self.skills.active_for_user(user_id=user_id)
        )
        needle = (query or "").strip().casefold()
        if needle:
            rows = [
                skill
                for skill in rows
                if needle in skill.canonical_name.casefold()
                or any(needle in alias.casefold() for alias in skill.aliases)
            ]
        if status is not None:
            rows = [skill for skill in rows if skill.confirmation_status is status]
        assessments = self._assessments(user_id, rows)
        if category is not None:
            rows = [
                skill
                for skill in rows
                if self._matches(assessments[skill.id], category, engagement)
            ]
        exposure = self._exposure(user_id, [skill.id for skill in rows])
        return [self._summary(skill, assessments[skill.id], exposure[skill.id]) for skill in rows]

    @staticmethod
    def _matches(
        assessment: Assessment, category: Category, engagement: EngagementType | None
    ) -> bool:
        if category not in assessment.categories:
            return False
        if engagement is None or category != "professional":
            return True
        return any(
            badge.evidence_class is EvidenceClass.PROFESSIONAL
            and badge.engagement_type is engagement
            for badge in assessment.badges
        )

    def skill_detail(self, *, user_id: uuid.UUID, skill_id: uuid.UUID) -> SkillDetail:
        skill = resolve_owned(self.session, Skill, user_id=user_id, id=skill_id)
        assessment = self._assessments(user_id, [skill])[skill.id]
        exposure = self._exposure(user_id, [skill.id])[skill.id]
        claims = self.claims.for_skill(user_id=user_id, skill_id=skill.id)
        summary = self._summary(skill, assessment, exposure)
        return SkillDetail(
            **summary.model_dump(),
            gap_note=skill.gap_note,
            user_note=skill.user_note,
            origin=skill.origin,
            claims=self._claim_responses(user_id, claims),
            created_at=skill.created_at,
        )

    def list_claims(
        self,
        *,
        user_id: uuid.UUID,
        status: ConfirmationStatus | None,
        evidence_class: EvidenceClass | None,
        skill_id: uuid.UUID | None,
        resume_id: uuid.UUID | None,
    ) -> list[ClaimResponse]:
        rows = self.claims.list_filtered(
            user_id=user_id,
            status=status,
            evidence_class=evidence_class,
            skill_id=skill_id,
            resume_id=resume_id,
        )
        return self._claim_responses(user_id, rows)

    def claim_detail(self, *, user_id: uuid.UUID, claim_id: uuid.UUID) -> ClaimResponse:
        claim = self.claims.get(user_id=user_id, id=claim_id)
        return self._claim_responses(user_id, [claim])[0]

    def _assessments(
        self, user_id: uuid.UUID, skills: Sequence[Skill]
    ) -> dict[uuid.UUID, Assessment]:
        facts = self.skills.claim_facts(user_id=user_id, skill_ids=[skill.id for skill in skills])
        return {
            skill.id: assess(facts[skill.id], marked_gap=skill.user_marked_gap) for skill in skills
        }

    def _exposure(
        self, user_id: uuid.UUID, skill_ids: Collection[uuid.UUID]
    ) -> dict[uuid.UUID, list[ResumeExposure]]:
        stated = self.skills.stated_resume_ids(user_id=user_id, skill_ids=skill_ids)
        mentioned = self.skills.mentioned_resume_ids(user_id=user_id, skill_ids=skill_ids)
        resumes = self.skills.resume_labels(
            user_id=user_id, resume_ids={resume_id for _, resume_id in stated | mentioned}
        )
        grouped: dict[uuid.UUID, list[ResumeExposure]] = {skill_id: [] for skill_id in skill_ids}
        for skill_id, resume_id in sorted(
            stated | mentioned, key=lambda pair: (str(pair[0]), resumes[pair[1]].label)
        ):
            resume: Resume = resumes[resume_id]
            grouped[skill_id].append(
                ResumeExposure(
                    resume_id=resume_id,
                    label=resume.label,
                    archived=resume.status is ResumeStatus.ARCHIVED,
                    stated=(skill_id, resume_id) in stated,
                    mentioned=(skill_id, resume_id) in mentioned,
                )
            )
        return grouped

    @staticmethod
    def _summary(
        skill: Skill, assessment: Assessment, exposure: list[ResumeExposure]
    ) -> SkillSummary:
        return SkillSummary(
            id=skill.id,
            canonical_name=skill.canonical_name,
            aliases=list(skill.aliases),
            confirmation_status=skill.confirmation_status,
            user_marked_gap=skill.user_marked_gap,
            headline=HeadlineResponse(
                category=assessment.headline.category,
                engagement_type=assessment.headline.engagement_type,
            ),
            categories=assessment.categories,
            badges=[
                BadgeResponse(
                    evidence_class=badge.evidence_class,
                    engagement_type=badge.engagement_type,
                    confirmed=badge.confirmed,
                    claim_count=badge.claim_count,
                )
                for badge in assessment.badges
            ],
            latest_end_date=assessment.latest_end_date,
            is_current=assessment.is_current,
            exposure=exposure,
            merged_into_skill_id=skill.merged_into_skill_id,
            state_version=skill.state_version,
            updated_at=skill.updated_at,
        )

    def _claim_responses(self, user_id: uuid.UUID, claims: Sequence[Claim]) -> list[ClaimResponse]:
        ids = [claim.id for claim in claims]
        sources = self.claims.sources_for(user_id=user_id, claim_ids=ids)
        skills = self.claims.skills_for(user_id=user_id, claim_ids=ids)
        artifact_ids = {source.artifact_id for items in sources.values() for source in items}
        resumes = {
            resume.artifact_id: resume
            for resume in self.session.scalars(
                select(Resume).where(
                    Resume.user_id == user_id, Resume.artifact_id.in_(list(artifact_ids))
                )
            )
        }
        return [
            ClaimResponse(
                id=claim.id,
                statement=claim.statement,
                evidence_class=claim.evidence_class,
                engagement_type=claim.engagement_type,
                confirmation_status=claim.confirmation_status,
                start_date=claim.start_date,
                end_date=claim.end_date,
                organization_label=claim.organization_label,
                origin=claim.origin,
                skills=[
                    SkillRef(id=s.id, canonical_name=s.canonical_name) for s in skills[claim.id]
                ],
                sources=[self._source(source, resumes) for source in sources[claim.id]],
                state_version=claim.state_version,
                created_at=claim.created_at,
                updated_at=claim.updated_at,
            )
            for claim in claims
        ]

    @staticmethod
    def _source(source: EvidenceSource, resumes: dict[uuid.UUID, Resume]) -> SourceResponse:
        resume = resumes.get(source.artifact_id) if source.artifact_id else None
        return SourceResponse(
            id=source.id,
            source_type=source.source_type,
            resume_id=None if resume is None else resume.id,
            resume_label=None if resume is None else resume.label,
            artifact_id=source.artifact_id,
            url=source.url,
            assertion_text=source.assertion_text,
            locator=source.locator,
            created_at=source.created_at,
        )

    def add_skill(
        self, *, user_id: uuid.UUID, name: str, aliases: list[str], user_note: str
    ) -> Skill:
        return self._commit(
            lambda: commands.add_skill(
                self.session,
                user_id=user_id,
                name=name,
                aliases=aliases,
                user_note=user_note,
                origin=EvidenceOrigin.USER,
            )
        )

    def edit_skill(
        self, *, user_id: uuid.UUID, skill_id: uuid.UUID, version: int, changes: dict[str, Any]
    ) -> Skill:
        return self._commit(
            lambda: commands.edit_skill(
                self.session,
                user_id=user_id,
                skill_id=skill_id,
                expected_state_version=version,
                changes=changes,
            )
        )

    def merge_skills(
        self,
        *,
        user_id: uuid.UUID,
        survivor_id: uuid.UUID,
        merged_id: uuid.UUID,
        survivor_version: int,
        merged_version: int,
    ) -> Skill:
        return self._commit(
            lambda: commands.merge_skills(
                self.session,
                user_id=user_id,
                survivor_id=survivor_id,
                merged_id=merged_id,
                expected_survivor_version=survivor_version,
                expected_merged_version=merged_version,
            )
        )

    def mark_gap(
        self, *, user_id: uuid.UUID, skill_id: uuid.UUID, version: int, note: str | None
    ) -> Skill:
        return self._commit(
            lambda: commands.mark_gap(
                self.session,
                user_id=user_id,
                skill_id=skill_id,
                expected_state_version=version,
                note=note,
            )
        )

    def clear_gap(self, *, user_id: uuid.UUID, skill_id: uuid.UUID, version: int) -> Skill:
        return self._commit(
            lambda: commands.clear_gap(
                self.session, user_id=user_id, skill_id=skill_id, expected_state_version=version
            )
        )

    def create_claim(self, *, user_id: uuid.UUID, body: ClaimCreate) -> Claim:
        return self._commit(
            lambda: commands.create_claim(
                self.session,
                user_id=user_id,
                statement=body.statement,
                evidence_class=body.evidence_class,
                engagement_type=body.engagement_type,
                start_date=body.start_date,
                end_date=body.end_date,
                organization_label=body.organization_label,
                origin=EvidenceOrigin.USER,
                sources=[source_input(source) for source in body.sources],
                skill_ids=body.skill_ids,
            )
        )

    def edit_claim(
        self, *, user_id: uuid.UUID, claim_id: uuid.UUID, version: int, changes: dict[str, Any]
    ) -> Claim:
        return self._commit(
            lambda: commands.edit_claim(
                self.session,
                user_id=user_id,
                claim_id=claim_id,
                expected_state_version=version,
                changes=changes,
            )
        )

    def change_classification(
        self,
        *,
        user_id: uuid.UUID,
        claim_id: uuid.UUID,
        version: int,
        evidence_class: EvidenceClass,
        engagement_type: EngagementType | None,
        confirmed: bool,
    ) -> Claim:
        return self._commit(
            lambda: commands.change_classification(
                self.session,
                user_id=user_id,
                claim_id=claim_id,
                expected_state_version=version,
                evidence_class=evidence_class,
                engagement_type=engagement_type,
                confirmed=confirmed,
            )
        )

    def reject_claim(self, *, user_id: uuid.UUID, claim_id: uuid.UUID, version: int) -> Claim:
        return self._commit(
            lambda: commands.reject_claim(
                self.session, user_id=user_id, claim_id=claim_id, expected_state_version=version
            )
        )

    def link_skill(self, *, user_id: uuid.UUID, claim_id: uuid.UUID, skill_id: uuid.UUID) -> Claim:
        return self._commit(
            lambda: commands.link_skill(
                self.session, user_id=user_id, claim_id=claim_id, skill_id=skill_id
            )
        )

    def unlink_skill(
        self, *, user_id: uuid.UUID, claim_id: uuid.UUID, skill_id: uuid.UUID
    ) -> Claim:
        return self._commit(
            lambda: commands.unlink_skill(
                self.session, user_id=user_id, claim_id=claim_id, skill_id=skill_id
            )
        )

    def add_source(self, *, user_id: uuid.UUID, claim_id: uuid.UUID, body: SourceCreate) -> Claim:
        return self._commit(
            lambda: commands.add_source(
                self.session, user_id=user_id, claim_id=claim_id, source=source_input(body)
            )
        )
