import uuid
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.clock import database_now
from app.db.models import (
    Actor,
    AggregateType,
    Artifact,
    Claim,
    ClaimSkill,
    ConfirmationStatus,
    EngagementType,
    EvidenceClass,
    EvidenceOrigin,
    EvidenceSource,
    EvidenceSourceType,
    Resume,
    Skill,
)
from app.db.tenancy import NotFound, resolve_owned
from app.db.versioning import ConcurrencyConflict, update_versioned
from app.events.payloads import EventPayload
from app.events.repository import DomainEventRepository
from app.evidence.assessment import BLOCKS_GAP
from app.evidence.events import (
    CLAIM_CONFIRMED,
    CLAIM_EDITED,
    CLAIM_REJECTED,
    EVIDENCE_CLASS_CHANGED,
    SKILL_ADDED,
    SKILL_CONFIRMED,
    SKILL_GAP_CLEARED,
    SKILL_GAP_MARKED,
    SKILL_MERGED,
    ClaimConfirmed,
    ClaimEdited,
    ClaimRejected,
    EvidenceClassChanged,
    SkillAdded,
    SkillConfirmed,
    SkillGapChanged,
    SkillMerged,
)
from app.evidence.normalize import MAX_ALIASES, clean_aliases, clean_name, skill_key, skill_keys
from app.evidence.repository import ClaimRepository, SkillRepository, lock_row

MAX_REDIRECT_DEPTH = 10
EDITABLE_CLAIM_FIELDS = ("statement", "start_date", "end_date", "organization_label")


@dataclass(frozen=True)
class SourceInput:
    source_type: EvidenceSourceType
    resume_id: uuid.UUID | None = None
    artifact_id: uuid.UUID | None = None
    url: str | None = None
    assertion_text: str | None = None
    locator: str | None = None
    message_id: uuid.UUID | None = None


def _emit(
    session: Session,
    *,
    user_id: uuid.UUID,
    aggregate_type: AggregateType,
    aggregate_id: uuid.UUID,
    event_type: str,
    payload: EventPayload,
    source_ref_id: uuid.UUID | None = None,
) -> None:
    DomainEventRepository(session).append(
        user_id=user_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        occurred_at=database_now(session),
        actor=Actor.USER,
        payload=payload,
        source_ref_id=source_ref_id,
    )


def follow_redirect(session: Session, skill: Skill) -> Skill:
    for _ in range(MAX_REDIRECT_DEPTH):
        if skill.merged_into_skill_id is None:
            return skill
        skill = resolve_owned(session, Skill, user_id=skill.user_id, id=skill.merged_into_skill_id)
    raise ApiError(409, "redirect_loop")


def resolve_skills(
    session: Session, *, user_id: uuid.UUID, skill_ids: Iterable[uuid.UUID]
) -> list[Skill]:
    resolved: dict[uuid.UUID, Skill] = {}
    for skill_id in skill_ids:
        skill = follow_redirect(
            session, resolve_owned(session, Skill, user_id=user_id, id=skill_id)
        )
        resolved.setdefault(skill.id, skill)
    return list(resolved.values())


def find_skill_by_name(session: Session, *, user_id: uuid.UUID, name: str) -> Skill | None:
    wanted = skill_key(name)
    if not wanted:
        return None
    for skill in SkillRepository(session).active_for_user(user_id=user_id):
        if wanted in skill_keys(skill.canonical_name, skill.aliases):
            return skill
    return None


def _require_free_keys(
    session: Session,
    *,
    user_id: uuid.UUID,
    keys: set[str],
    exclude_id: uuid.UUID | None,
) -> None:
    for other in SkillRepository(session).active_for_user(user_id=user_id):
        if other.id != exclude_id and keys & skill_keys(other.canonical_name, other.aliases):
            raise ApiError(409, "skill_exists")


def _valid_name(name: str) -> str:
    cleaned = clean_name(name)
    if not skill_key(cleaned):
        raise ApiError(422, "invalid_name")
    return cleaned


def add_skill(
    session: Session,
    *,
    user_id: uuid.UUID,
    name: str,
    aliases: Sequence[str],
    user_note: str,
    origin: EvidenceOrigin,
    review_item_id: uuid.UUID | None = None,
    llm_run_id: uuid.UUID | None = None,
) -> Skill:
    SkillRepository(session).lock_names(user_id=user_id)
    canonical = _valid_name(name)
    cleaned = clean_aliases(aliases, canonical_name=canonical)
    _require_free_keys(
        session, user_id=user_id, keys=skill_keys(canonical, cleaned), exclude_id=None
    )
    skill = Skill(
        user_id=user_id,
        canonical_name=canonical,
        normalized_key=skill_key(canonical),
        aliases=cleaned,
        confirmation_status=ConfirmationStatus.CONFIRMED,
        user_note=user_note,
        origin=origin,
        llm_run_id=llm_run_id,
    )
    session.add(skill)
    session.flush()
    if origin is EvidenceOrigin.USER:
        _emit(
            session,
            user_id=user_id,
            aggregate_type=AggregateType.SKILL,
            aggregate_id=skill.id,
            event_type=SKILL_ADDED,
            payload=SkillAdded(skill_id=skill.id, origin=origin.value),
        )
    else:
        _emit(
            session,
            user_id=user_id,
            aggregate_type=AggregateType.SKILL,
            aggregate_id=skill.id,
            event_type=SKILL_CONFIRMED,
            payload=SkillConfirmed(
                skill_id=skill.id,
                origin=origin.value,
                review_item_id=review_item_id,
                llm_run_id=llm_run_id,
            ),
            source_ref_id=review_item_id,
        )
    return skill


def ensure_skill(
    session: Session,
    *,
    user_id: uuid.UUID,
    name: str,
    origin: EvidenceOrigin,
    review_item_id: uuid.UUID | None,
    llm_run_id: uuid.UUID | None,
) -> tuple[Skill, bool]:
    SkillRepository(session).lock_names(user_id=user_id)
    existing = find_skill_by_name(session, user_id=user_id, name=name)
    if existing is not None:
        return existing, False
    skill = add_skill(
        session,
        user_id=user_id,
        name=name,
        aliases=[],
        user_note="",
        origin=origin,
        review_item_id=review_item_id,
        llm_run_id=llm_run_id,
    )
    return skill, True


def edit_skill(
    session: Session,
    *,
    user_id: uuid.UUID,
    skill_id: uuid.UUID,
    expected_state_version: int,
    changes: dict[str, Any],
) -> Skill:
    repository = SkillRepository(session)
    repository.lock_names(user_id=user_id)
    skill = lock_row(session, Skill, user_id=user_id, id=skill_id)
    if skill.state_version != expected_state_version:
        raise ConcurrencyConflict("skills")
    if skill.merged_into_skill_id is not None:
        raise ApiError(409, "skill_merged")
    canonical = skill.canonical_name
    if changes.get("canonical_name") is not None:
        canonical = _valid_name(changes["canonical_name"])
    aliases = changes["aliases"] if changes.get("aliases") is not None else skill.aliases
    cleaned = clean_aliases(aliases, canonical_name=canonical)
    _require_free_keys(
        session, user_id=user_id, keys=skill_keys(canonical, cleaned), exclude_id=skill.id
    )
    values: dict[str, Any] = {
        "canonical_name": canonical,
        "normalized_key": skill_key(canonical),
        "aliases": cleaned,
        "updated_at": database_now(session),
    }
    if changes.get("user_note") is not None:
        values["user_note"] = changes["user_note"]
    update_versioned(
        session,
        Skill.__table__,  # type: ignore[arg-type]
        user_id=user_id,
        id=skill.id,
        expected_version=expected_state_version,
        values=values,
    )
    session.refresh(skill)
    return skill


def merge_skills(
    session: Session,
    *,
    user_id: uuid.UUID,
    survivor_id: uuid.UUID,
    merged_id: uuid.UUID,
    expected_survivor_version: int,
    expected_merged_version: int,
) -> Skill:
    if survivor_id == merged_id:
        raise ApiError(422, "merge_same_skill")
    repository = SkillRepository(session)
    claims = ClaimRepository(session)
    repository.lock_names(user_id=user_id)
    locked = {
        skill_id: lock_row(session, Skill, user_id=user_id, id=skill_id)
        for skill_id in sorted((survivor_id, merged_id), key=str)
    }
    survivor, merged = locked[survivor_id], locked[merged_id]
    if survivor.state_version != expected_survivor_version:
        raise ConcurrencyConflict("skills")
    if merged.state_version != expected_merged_version:
        raise ConcurrencyConflict("skills")
    if survivor.merged_into_skill_id is not None or merged.merged_into_skill_id is not None:
        raise ApiError(409, "skill_merged")
    kept_claims = {
        link.claim_id for link in claims.links_for_skill(user_id=user_id, skill_id=survivor.id)
    }
    moved = dropped = 0
    drop_ids: list[uuid.UUID] = []
    for link in claims.links_for_skill(user_id=user_id, skill_id=merged.id):
        if link.claim_id in kept_claims:
            drop_ids.append(link.id)
            dropped += 1
        else:
            link.skill_id = survivor.id
            moved += 1
    claims.delete_links(user_id=user_id, link_ids=drop_ids)
    session.flush()
    absorbed = clean_aliases(
        [*survivor.aliases, merged.canonical_name, *merged.aliases],
        canonical_name=survivor.canonical_name,
    )
    if len(absorbed) > MAX_ALIASES:
        raise ApiError(422, "alias_limit_exceeded")
    survivor_gap_cleared = survivor.user_marked_gap and repository.has_gap_blocking_evidence(
        user_id=user_id, skill_id=survivor.id
    )
    now = database_now(session)
    update_versioned(
        session,
        Skill.__table__,  # type: ignore[arg-type]
        user_id=user_id,
        id=merged.id,
        expected_version=expected_merged_version,
        values={
            "merged_into_skill_id": survivor.id,
            "user_marked_gap": False,
            "gap_note": None,
            "updated_at": now,
        },
    )
    survivor_values: dict[str, Any] = {"aliases": absorbed, "updated_at": now}
    if survivor_gap_cleared:
        survivor_values.update(user_marked_gap=False, gap_note=None)
    update_versioned(
        session,
        Skill.__table__,  # type: ignore[arg-type]
        user_id=user_id,
        id=survivor.id,
        expected_version=expected_survivor_version,
        values=survivor_values,
    )
    _emit(
        session,
        user_id=user_id,
        aggregate_type=AggregateType.SKILL,
        aggregate_id=survivor.id,
        event_type=SKILL_MERGED,
        payload=SkillMerged(
            survivor_id=survivor.id,
            merged_id=merged.id,
            moved_links=moved,
            dropped_duplicate_links=dropped,
            survivor_gap_cleared=survivor_gap_cleared,
        ),
    )
    if survivor_gap_cleared:
        _emit(
            session,
            user_id=user_id,
            aggregate_type=AggregateType.SKILL,
            aggregate_id=survivor.id,
            event_type=SKILL_GAP_CLEARED,
            payload=SkillGapChanged(skill_id=survivor.id),
        )
    session.refresh(survivor)
    return survivor


def mark_gap(
    session: Session,
    *,
    user_id: uuid.UUID,
    skill_id: uuid.UUID,
    expected_state_version: int,
    note: str | None,
) -> Skill:
    skill = lock_row(session, Skill, user_id=user_id, id=skill_id)
    if skill.state_version != expected_state_version:
        raise ConcurrencyConflict("skills")
    if skill.merged_into_skill_id is not None:
        raise ApiError(409, "skill_merged")
    if skill.user_marked_gap:
        raise ApiError(409, "invalid_state")
    if SkillRepository(session).has_gap_blocking_evidence(user_id=user_id, skill_id=skill.id):
        raise ApiError(409, "gap_refused_evidence_exists")
    update_versioned(
        session,
        Skill.__table__,  # type: ignore[arg-type]
        user_id=user_id,
        id=skill.id,
        expected_version=expected_state_version,
        values={
            "user_marked_gap": True,
            "gap_note": note or None,
            "updated_at": database_now(session),
        },
    )
    _emit(
        session,
        user_id=user_id,
        aggregate_type=AggregateType.SKILL,
        aggregate_id=skill.id,
        event_type=SKILL_GAP_MARKED,
        payload=SkillGapChanged(skill_id=skill.id),
    )
    session.refresh(skill)
    return skill


def clear_gap(
    session: Session, *, user_id: uuid.UUID, skill_id: uuid.UUID, expected_state_version: int
) -> Skill:
    skill = lock_row(session, Skill, user_id=user_id, id=skill_id)
    if skill.state_version != expected_state_version:
        raise ConcurrencyConflict("skills")
    if not skill.user_marked_gap:
        raise ApiError(409, "invalid_state")
    update_versioned(
        session,
        Skill.__table__,  # type: ignore[arg-type]
        user_id=user_id,
        id=skill.id,
        expected_version=expected_state_version,
        values={"user_marked_gap": False, "gap_note": None, "updated_at": database_now(session)},
    )
    _emit(
        session,
        user_id=user_id,
        aggregate_type=AggregateType.SKILL,
        aggregate_id=skill.id,
        event_type=SKILL_GAP_CLEARED,
        payload=SkillGapChanged(skill_id=skill.id),
    )
    session.refresh(skill)
    return skill


def _require_engagement(
    evidence_class: EvidenceClass, engagement_type: EngagementType | None
) -> EngagementType | None:
    if evidence_class is EvidenceClass.PROFESSIONAL:
        if engagement_type is None:
            raise ApiError(422, "engagement_type_required")
        return engagement_type
    if engagement_type is not None:
        raise ApiError(422, "engagement_type_only_professional")
    return None


def _refuse_gap_conflict(evidence_class: EvidenceClass, skills: Iterable[Skill]) -> None:
    if evidence_class in BLOCKS_GAP and any(skill.user_marked_gap for skill in skills):
        raise ApiError(409, "gap_marked")


def _build_source(
    session: Session, *, user_id: uuid.UUID, claim_id: uuid.UUID, source: SourceInput
) -> EvidenceSource:
    artifact_id = source.artifact_id
    match source.source_type:
        case EvidenceSourceType.RESUME:
            if source.resume_id is None:
                raise ApiError(422, "invalid_source")
            artifact_id = resolve_owned(
                session, Resume, user_id=user_id, id=source.resume_id
            ).artifact_id
        case EvidenceSourceType.ARTIFACT:
            if artifact_id is None:
                raise ApiError(422, "invalid_source")
            resolve_owned(session, Artifact, user_id=user_id, id=artifact_id)
        case EvidenceSourceType.PROJECT_URL:
            parsed = urlparse(source.url or "")
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ApiError(422, "invalid_source")
            artifact_id = None
        case EvidenceSourceType.USER_ASSERTION:
            if not (source.assertion_text or "").strip():
                raise ApiError(422, "invalid_source")
            artifact_id = None
    is_assertion = source.source_type is EvidenceSourceType.USER_ASSERTION
    return EvidenceSource(
        user_id=user_id,
        claim_id=claim_id,
        source_type=source.source_type,
        artifact_id=artifact_id,
        message_id=source.message_id if is_assertion else None,
        locator=source.locator[:500] if source.locator else None,
        url=source.url if source.source_type is EvidenceSourceType.PROJECT_URL else None,
        assertion_text=source.assertion_text.strip()
        if is_assertion and source.assertion_text
        else None,
    )


def create_claim(
    session: Session,
    *,
    user_id: uuid.UUID,
    statement: str,
    evidence_class: EvidenceClass,
    engagement_type: EngagementType | None,
    start_date: date | None,
    end_date: date | None,
    organization_label: str | None,
    origin: EvidenceOrigin,
    sources: Sequence[SourceInput],
    skill_ids: Collection[uuid.UUID],
    llm_run_id: uuid.UUID | None = None,
    review_item_id: uuid.UUID | None = None,
) -> Claim:
    if not sources:
        raise ApiError(422, "source_required")
    engagement = _require_engagement(evidence_class, engagement_type)
    skills = resolve_skills(session, user_id=user_id, skill_ids=skill_ids)
    _refuse_gap_conflict(evidence_class, skills)
    claim = Claim(
        user_id=user_id,
        statement=statement,
        evidence_class=evidence_class,
        engagement_type=engagement,
        confirmation_status=ConfirmationStatus.CONFIRMED,
        start_date=start_date,
        end_date=end_date,
        organization_label=organization_label,
        origin=origin,
        llm_run_id=llm_run_id,
    )
    session.add(claim)
    session.flush()
    for source in sources:
        session.add(_build_source(session, user_id=user_id, claim_id=claim.id, source=source))
    for skill in skills:
        session.add(ClaimSkill(user_id=user_id, claim_id=claim.id, skill_id=skill.id))
    session.flush()
    SkillRepository(session).touch(user_id=user_id, skill_ids=[skill.id for skill in skills])
    _emit(
        session,
        user_id=user_id,
        aggregate_type=AggregateType.CLAIM,
        aggregate_id=claim.id,
        event_type=CLAIM_CONFIRMED,
        payload=ClaimConfirmed(
            claim_id=claim.id,
            origin=origin.value,
            evidence_class=evidence_class.value,
            engagement_type=None if engagement is None else engagement.value,
            skill_ids=[skill.id for skill in skills],
            review_item_id=review_item_id,
            llm_run_id=llm_run_id,
        ),
        source_ref_id=review_item_id,
    )
    return claim


def _touch_claim_skills(session: Session, *, user_id: uuid.UUID, claim_id: uuid.UUID) -> None:
    SkillRepository(session).touch(
        user_id=user_id,
        skill_ids=ClaimRepository(session).linked_skill_ids(user_id=user_id, claim_id=claim_id),
    )


def _locked_claim(
    session: Session, *, user_id: uuid.UUID, claim_id: uuid.UUID, expected_state_version: int
) -> Claim:
    claim = lock_row(session, Claim, user_id=user_id, id=claim_id)
    if claim.state_version != expected_state_version:
        raise ConcurrencyConflict("claims")
    if claim.confirmation_status is ConfirmationStatus.REJECTED:
        raise ApiError(409, "claim_rejected")
    return claim


def edit_claim(
    session: Session,
    *,
    user_id: uuid.UUID,
    claim_id: uuid.UUID,
    expected_state_version: int,
    changes: dict[str, Any],
) -> Claim:
    claim = _locked_claim(
        session, user_id=user_id, claim_id=claim_id, expected_state_version=expected_state_version
    )
    values = {
        name: changes[name]
        for name in EDITABLE_CLAIM_FIELDS
        if name in changes and changes[name] != getattr(claim, name)
    }
    start = values.get("start_date", claim.start_date)
    end = values.get("end_date", claim.end_date)
    if start is not None and end is not None and end < start:
        raise ApiError(422, "dates_out_of_order")
    if not values:
        return claim
    update_versioned(
        session,
        Claim.__table__,  # type: ignore[arg-type]
        user_id=user_id,
        id=claim.id,
        expected_version=expected_state_version,
        values={**values, "updated_at": database_now(session)},
    )
    _touch_claim_skills(session, user_id=user_id, claim_id=claim.id)
    _emit(
        session,
        user_id=user_id,
        aggregate_type=AggregateType.CLAIM,
        aggregate_id=claim.id,
        event_type=CLAIM_EDITED,
        payload=ClaimEdited(claim_id=claim.id, fields=sorted(values)),
    )
    session.refresh(claim)
    return claim


def change_classification(
    session: Session,
    *,
    user_id: uuid.UUID,
    claim_id: uuid.UUID,
    expected_state_version: int,
    evidence_class: EvidenceClass,
    engagement_type: EngagementType | None,
    confirmed: bool,
    review_item_id: uuid.UUID | None = None,
) -> Claim:
    if not confirmed:
        raise ApiError(422, "confirmation_required")
    claim = _locked_claim(
        session, user_id=user_id, claim_id=claim_id, expected_state_version=expected_state_version
    )
    engagement = _require_engagement(evidence_class, engagement_type)
    if (claim.evidence_class, claim.engagement_type) == (evidence_class, engagement):
        raise ApiError(422, "unchanged")
    skills = resolve_skills(
        session,
        user_id=user_id,
        skill_ids=ClaimRepository(session).linked_skill_ids(user_id=user_id, claim_id=claim.id),
    )
    _refuse_gap_conflict(evidence_class, skills)
    old_class, old_engagement = claim.evidence_class, claim.engagement_type
    update_versioned(
        session,
        Claim.__table__,  # type: ignore[arg-type]
        user_id=user_id,
        id=claim.id,
        expected_version=expected_state_version,
        values={
            "evidence_class": evidence_class,
            "engagement_type": engagement,
            "updated_at": database_now(session),
        },
    )
    SkillRepository(session).touch(user_id=user_id, skill_ids=[skill.id for skill in skills])
    _emit(
        session,
        user_id=user_id,
        aggregate_type=AggregateType.CLAIM,
        aggregate_id=claim.id,
        event_type=EVIDENCE_CLASS_CHANGED,
        payload=EvidenceClassChanged(
            claim_id=claim.id,
            old_evidence_class=old_class.value,
            new_evidence_class=evidence_class.value,
            old_engagement_type=None if old_engagement is None else old_engagement.value,
            new_engagement_type=None if engagement is None else engagement.value,
            review_item_id=review_item_id,
        ),
        source_ref_id=review_item_id,
    )
    session.refresh(claim)
    return claim


def reject_claim(
    session: Session, *, user_id: uuid.UUID, claim_id: uuid.UUID, expected_state_version: int
) -> Claim:
    claim = _locked_claim(
        session, user_id=user_id, claim_id=claim_id, expected_state_version=expected_state_version
    )
    previous = claim.confirmation_status
    update_versioned(
        session,
        Claim.__table__,  # type: ignore[arg-type]
        user_id=user_id,
        id=claim.id,
        expected_version=expected_state_version,
        values={
            "confirmation_status": ConfirmationStatus.REJECTED,
            "updated_at": database_now(session),
        },
    )
    _touch_claim_skills(session, user_id=user_id, claim_id=claim.id)
    _emit(
        session,
        user_id=user_id,
        aggregate_type=AggregateType.CLAIM,
        aggregate_id=claim.id,
        event_type=CLAIM_REJECTED,
        payload=ClaimRejected(claim_id=claim.id, from_status=previous.value),
    )
    session.refresh(claim)
    return claim


def link_skill(
    session: Session, *, user_id: uuid.UUID, claim_id: uuid.UUID, skill_id: uuid.UUID
) -> Claim:
    claim = lock_row(session, Claim, user_id=user_id, id=claim_id)
    if claim.confirmation_status is ConfirmationStatus.REJECTED:
        raise ApiError(409, "claim_rejected")
    (skill,) = resolve_skills(session, user_id=user_id, skill_ids=[skill_id])
    repository = ClaimRepository(session)
    if repository.find_link(user_id=user_id, claim_id=claim.id, skill_id=skill.id) is not None:
        return claim
    _refuse_gap_conflict(claim.evidence_class, [skill])
    session.add(ClaimSkill(user_id=user_id, claim_id=claim.id, skill_id=skill.id))
    session.flush()
    _after_link_change(session, user_id=user_id, claim=claim, touched=[skill.id])
    return claim


def unlink_skill(
    session: Session, *, user_id: uuid.UUID, claim_id: uuid.UUID, skill_id: uuid.UUID
) -> Claim:
    claim = lock_row(session, Claim, user_id=user_id, id=claim_id)
    link = ClaimRepository(session).find_link(user_id=user_id, claim_id=claim.id, skill_id=skill_id)
    if link is None:
        raise NotFound("ClaimSkill")
    ClaimRepository(session).delete_links(user_id=user_id, link_ids=[link.id])
    session.flush()
    _after_link_change(session, user_id=user_id, claim=claim, touched=[skill_id])
    return claim


def _touch_claim(session: Session, *, user_id: uuid.UUID, claim_id: uuid.UUID) -> None:
    session.execute(
        update(Claim)
        .where(Claim.user_id == user_id, Claim.id == claim_id)
        .values(updated_at=database_now(session))
        .execution_options(synchronize_session=False)
    )


def _after_link_change(
    session: Session, *, user_id: uuid.UUID, claim: Claim, touched: Collection[uuid.UUID]
) -> None:
    SkillRepository(session).touch(user_id=user_id, skill_ids=touched)
    _touch_claim(session, user_id=user_id, claim_id=claim.id)
    _emit(
        session,
        user_id=user_id,
        aggregate_type=AggregateType.CLAIM,
        aggregate_id=claim.id,
        event_type=CLAIM_EDITED,
        payload=ClaimEdited(claim_id=claim.id, fields=["skills"]),
    )
    session.refresh(claim)


def add_source(
    session: Session, *, user_id: uuid.UUID, claim_id: uuid.UUID, source: SourceInput
) -> Claim:
    claim = lock_row(session, Claim, user_id=user_id, id=claim_id)
    if claim.confirmation_status is ConfirmationStatus.REJECTED:
        raise ApiError(409, "claim_rejected")
    session.add(_build_source(session, user_id=user_id, claim_id=claim.id, source=source))
    session.flush()
    _touch_claim_skills(session, user_id=user_id, claim_id=claim.id)
    _touch_claim(session, user_id=user_id, claim_id=claim.id)
    _emit(
        session,
        user_id=user_id,
        aggregate_type=AggregateType.CLAIM,
        aggregate_id=claim.id,
        event_type=CLAIM_EDITED,
        payload=ClaimEdited(claim_id=claim.id, fields=["sources"]),
    )
    session.refresh(claim)
    return claim
