import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.deps import current_auth, get_db_session, verify_csrf
from app.auth.service import AuthContext
from app.core.errors import ErrorResponse
from app.db.models import ConfirmationStatus, EngagementType, EvidenceClass
from app.evidence.assessment import Category
from app.evidence.schemas import (
    ClaimCreate,
    ClaimPatch,
    ClaimResponse,
    ClassificationRequest,
    ClearGapRequest,
    LinkSkillRequest,
    MarkGapRequest,
    RejectClaimRequest,
    SkillCreate,
    SkillDetail,
    SkillMergeRequest,
    SkillPatch,
    SkillSummary,
    SourceCreate,
)
from app.evidence.service import EvidenceService

router = APIRouter(
    prefix="/api/v1",
    tags=["evidence"],
    dependencies=[Depends(verify_csrf)],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)

NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"model": ErrorResponse}}
COMMAND_ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}

Auth = Annotated[AuthContext, Depends(current_auth)]
DbSession = Annotated[Session, Depends(get_db_session)]


def evidence_service(session: DbSession) -> EvidenceService:
    return EvidenceService(session)


Evidence = Annotated[EvidenceService, Depends(evidence_service)]


@router.get("/skills", response_model=list[SkillSummary])
def list_skills(
    auth: Auth,
    service: Evidence,
    q: Annotated[str | None, Query(max_length=100)] = None,
    category: Category | None = None,
    engagement: EngagementType | None = None,
    status: ConfirmationStatus | None = None,
    include_merged: bool = False,
) -> list[SkillSummary]:
    return service.list_skills(
        user_id=auth.user_id,
        query=q,
        category=category,
        engagement=engagement,
        status=status,
        include_merged=include_merged,
    )


@router.post("/skills", response_model=SkillDetail, status_code=201, responses=COMMAND_ERRORS)
def add_skill(body: SkillCreate, auth: Auth, service: Evidence) -> SkillDetail:
    skill = service.add_skill(
        user_id=auth.user_id,
        name=body.canonical_name,
        aliases=body.aliases,
        user_note=body.user_note,
    )
    return service.skill_detail(user_id=auth.user_id, skill_id=skill.id)


@router.get("/skills/{skill_id}", response_model=SkillDetail, responses=NOT_FOUND)
def get_skill(skill_id: uuid.UUID, auth: Auth, service: Evidence) -> SkillDetail:
    return service.skill_detail(user_id=auth.user_id, skill_id=skill_id)


@router.patch("/skills/{skill_id}", response_model=SkillDetail, responses=COMMAND_ERRORS)
def edit_skill(skill_id: uuid.UUID, body: SkillPatch, auth: Auth, service: Evidence) -> SkillDetail:
    service.edit_skill(
        user_id=auth.user_id,
        skill_id=skill_id,
        version=body.expected_state_version,
        changes=body.model_dump(exclude_unset=True, exclude={"expected_state_version"}),
    )
    return service.skill_detail(user_id=auth.user_id, skill_id=skill_id)


@router.post("/skills/{skill_id}/merge", response_model=SkillDetail, responses=COMMAND_ERRORS)
def merge_skills(
    skill_id: uuid.UUID, body: SkillMergeRequest, auth: Auth, service: Evidence
) -> SkillDetail:
    service.merge_skills(
        user_id=auth.user_id,
        survivor_id=skill_id,
        merged_id=body.merged_id,
        survivor_version=body.expected_state_version,
        merged_version=body.expected_merged_state_version,
    )
    return service.skill_detail(user_id=auth.user_id, skill_id=skill_id)


@router.post("/skills/{skill_id}/mark-gap", response_model=SkillDetail, responses=COMMAND_ERRORS)
def mark_gap(
    skill_id: uuid.UUID, body: MarkGapRequest, auth: Auth, service: Evidence
) -> SkillDetail:
    service.mark_gap(
        user_id=auth.user_id,
        skill_id=skill_id,
        version=body.expected_state_version,
        note=body.note,
    )
    return service.skill_detail(user_id=auth.user_id, skill_id=skill_id)


@router.post("/skills/{skill_id}/clear-gap", response_model=SkillDetail, responses=COMMAND_ERRORS)
def clear_gap(
    skill_id: uuid.UUID, body: ClearGapRequest, auth: Auth, service: Evidence
) -> SkillDetail:
    service.clear_gap(user_id=auth.user_id, skill_id=skill_id, version=body.expected_state_version)
    return service.skill_detail(user_id=auth.user_id, skill_id=skill_id)


@router.get("/claims", response_model=list[ClaimResponse])
def list_claims(
    auth: Auth,
    service: Evidence,
    status: ConfirmationStatus | None = None,
    evidence_class: EvidenceClass | None = None,
    skill_id: uuid.UUID | None = None,
    resume_id: uuid.UUID | None = None,
) -> list[ClaimResponse]:
    return service.list_claims(
        user_id=auth.user_id,
        status=status,
        evidence_class=evidence_class,
        skill_id=skill_id,
        resume_id=resume_id,
    )


@router.post("/claims", response_model=ClaimResponse, status_code=201, responses=COMMAND_ERRORS)
def create_claim(body: ClaimCreate, auth: Auth, service: Evidence) -> ClaimResponse:
    claim = service.create_claim(user_id=auth.user_id, body=body)
    return service.claim_detail(user_id=auth.user_id, claim_id=claim.id)


@router.get("/claims/{claim_id}", response_model=ClaimResponse, responses=NOT_FOUND)
def get_claim(claim_id: uuid.UUID, auth: Auth, service: Evidence) -> ClaimResponse:
    return service.claim_detail(user_id=auth.user_id, claim_id=claim_id)


@router.patch("/claims/{claim_id}", response_model=ClaimResponse, responses=COMMAND_ERRORS)
def edit_claim(
    claim_id: uuid.UUID, body: ClaimPatch, auth: Auth, service: Evidence
) -> ClaimResponse:
    service.edit_claim(
        user_id=auth.user_id,
        claim_id=claim_id,
        version=body.expected_state_version,
        changes=body.model_dump(exclude_unset=True, exclude={"expected_state_version"}),
    )
    return service.claim_detail(user_id=auth.user_id, claim_id=claim_id)


@router.post(
    "/claims/{claim_id}/classification", response_model=ClaimResponse, responses=COMMAND_ERRORS
)
def change_classification(
    claim_id: uuid.UUID, body: ClassificationRequest, auth: Auth, service: Evidence
) -> ClaimResponse:
    service.change_classification(
        user_id=auth.user_id,
        claim_id=claim_id,
        version=body.expected_state_version,
        evidence_class=body.evidence_class,
        engagement_type=body.engagement_type,
        confirmed=body.confirm_change,
    )
    return service.claim_detail(user_id=auth.user_id, claim_id=claim_id)


@router.post("/claims/{claim_id}/reject", response_model=ClaimResponse, responses=COMMAND_ERRORS)
def reject_claim(
    claim_id: uuid.UUID, body: RejectClaimRequest, auth: Auth, service: Evidence
) -> ClaimResponse:
    service.reject_claim(
        user_id=auth.user_id, claim_id=claim_id, version=body.expected_state_version
    )
    return service.claim_detail(user_id=auth.user_id, claim_id=claim_id)


@router.post("/claims/{claim_id}/skills", response_model=ClaimResponse, responses=COMMAND_ERRORS)
def link_skill(
    claim_id: uuid.UUID, body: LinkSkillRequest, auth: Auth, service: Evidence
) -> ClaimResponse:
    service.link_skill(user_id=auth.user_id, claim_id=claim_id, skill_id=body.skill_id)
    return service.claim_detail(user_id=auth.user_id, claim_id=claim_id)


@router.delete(
    "/claims/{claim_id}/skills/{skill_id}", response_model=ClaimResponse, responses=COMMAND_ERRORS
)
def unlink_skill(
    claim_id: uuid.UUID, skill_id: uuid.UUID, auth: Auth, service: Evidence
) -> ClaimResponse:
    service.unlink_skill(user_id=auth.user_id, claim_id=claim_id, skill_id=skill_id)
    return service.claim_detail(user_id=auth.user_id, claim_id=claim_id)


@router.post("/claims/{claim_id}/sources", response_model=ClaimResponse, responses=COMMAND_ERRORS)
def add_source(
    claim_id: uuid.UUID, body: SourceCreate, auth: Auth, service: Evidence
) -> ClaimResponse:
    service.add_source(user_id=auth.user_id, claim_id=claim_id, body=body)
    return service.claim_detail(user_id=auth.user_id, claim_id=claim_id)
