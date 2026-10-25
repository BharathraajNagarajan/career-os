from app.core.errors import ApiError
from app.db.models import EvidenceOrigin, EvidenceSourceType, ProposalType, Resume
from app.db.tenancy import NotFound, resolve_owned
from app.evidence.commands import SourceInput, create_claim, ensure_skill, record_class_change
from app.evidence.proposals import ClaimProposal, SkillProposal
from app.review.handlers import ReviewContext, ReviewHandler, ReviewHandlerRegistry
from app.review.repository import ReviewItemRepository


def _require_resume(context: ReviewContext, proposal: ClaimProposal | SkillProposal) -> None:
    try:
        resolve_owned(context.session, Resume, user_id=context.user_id, id=proposal.resume_id)
    except NotFound as exc:
        raise ApiError(409, "target_missing") from exc


def confirm_skill(context: ReviewContext, payload: SkillProposal) -> None:
    _require_resume(context, payload)
    ensure_skill(
        context.session,
        user_id=context.user_id,
        name=payload.name,
        origin=EvidenceOrigin.EXTRACTED,
        review_item_id=context.review_item_id,
        llm_run_id=context.llm_run_id,
    )


def confirm_claim(context: ReviewContext, payload: ClaimProposal) -> None:
    _require_resume(context, payload)
    item = ReviewItemRepository(context.session).get(
        user_id=context.user_id, id=context.review_item_id
    )
    proposed = ClaimProposal.model_validate(item.proposed_payload)
    old = (proposed.evidence_class, proposed.engagement_type)
    new = (payload.evidence_class, payload.engagement_type)
    if old != new and not payload.confirm_class_change:
        raise ApiError(422, "confirmation_required")
    skills = [
        ensure_skill(
            context.session,
            user_id=context.user_id,
            name=name,
            origin=EvidenceOrigin.EXTRACTED,
            review_item_id=context.review_item_id,
            llm_run_id=context.llm_run_id,
        )[0]
        for name in payload.skill_names
    ]
    claim = create_claim(
        context.session,
        user_id=context.user_id,
        statement=payload.statement,
        evidence_class=payload.evidence_class,
        engagement_type=payload.engagement_type,
        start_date=payload.start_date,
        end_date=payload.end_date,
        organization_label=payload.organization_label,
        origin=EvidenceOrigin.EXTRACTED,
        sources=[SourceInput(source_type=EvidenceSourceType.RESUME, resume_id=payload.resume_id)],
        skill_ids=[skill.id for skill in skills],
        llm_run_id=context.llm_run_id,
        review_item_id=context.review_item_id,
    )
    if old != new:
        record_class_change(
            context.session,
            user_id=context.user_id,
            claim_id=claim.id,
            old=old,
            new=new,
            review_item_id=context.review_item_id,
        )


def register_evidence_handlers(registry: ReviewHandlerRegistry) -> None:
    registry.register(ReviewHandler(ProposalType.CLAIM, ClaimProposal, confirm_claim))
    registry.register(ReviewHandler(ProposalType.SKILL, SkillProposal, confirm_skill))
