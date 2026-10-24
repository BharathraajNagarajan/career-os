import uuid

from pydantic import Field

from app.events.payloads import EventPayload, payload_registry

SKILL_ADDED = "SKILL_ADDED"
SKILL_CONFIRMED = "SKILL_CONFIRMED"
SKILL_MERGED = "SKILL_MERGED"
SKILL_GAP_MARKED = "SKILL_GAP_MARKED"
SKILL_GAP_CLEARED = "SKILL_GAP_CLEARED"
CLAIM_CONFIRMED = "CLAIM_CONFIRMED"
CLAIM_REJECTED = "CLAIM_REJECTED"
CLAIM_EDITED = "CLAIM_EDITED"
EVIDENCE_CLASS_CHANGED = "EVIDENCE_CLASS_CHANGED"


class SkillAdded(EventPayload):
    schema_version: int = 1
    skill_id: uuid.UUID
    origin: str


class SkillConfirmed(EventPayload):
    schema_version: int = 1
    skill_id: uuid.UUID
    origin: str
    review_item_id: uuid.UUID | None
    llm_run_id: uuid.UUID | None


class SkillMerged(EventPayload):
    schema_version: int = 1
    survivor_id: uuid.UUID
    merged_id: uuid.UUID
    moved_links: int
    dropped_duplicate_links: int
    survivor_gap_cleared: bool


class SkillGapChanged(EventPayload):
    schema_version: int = 1
    skill_id: uuid.UUID


class ClaimConfirmed(EventPayload):
    schema_version: int = 1
    claim_id: uuid.UUID
    origin: str
    evidence_class: str
    engagement_type: str | None
    skill_ids: list[uuid.UUID] = Field(max_length=50)
    review_item_id: uuid.UUID | None
    llm_run_id: uuid.UUID | None


class ClaimRejected(EventPayload):
    schema_version: int = 1
    claim_id: uuid.UUID
    from_status: str


class ClaimEdited(EventPayload):
    schema_version: int = 1
    claim_id: uuid.UUID
    fields: list[str] = Field(max_length=10)


class EvidenceClassChanged(EventPayload):
    schema_version: int = 1
    claim_id: uuid.UUID
    old_evidence_class: str
    new_evidence_class: str
    old_engagement_type: str | None
    new_engagement_type: str | None
    review_item_id: uuid.UUID | None


payload_registry.register(SKILL_ADDED, SkillAdded, version=1)
payload_registry.register(SKILL_CONFIRMED, SkillConfirmed, version=1)
payload_registry.register(SKILL_MERGED, SkillMerged, version=1)
payload_registry.register(SKILL_GAP_MARKED, SkillGapChanged, version=1)
payload_registry.register(SKILL_GAP_CLEARED, SkillGapChanged, version=1)
payload_registry.register(CLAIM_CONFIRMED, ClaimConfirmed, version=1)
payload_registry.register(CLAIM_REJECTED, ClaimRejected, version=1)
payload_registry.register(CLAIM_EDITED, ClaimEdited, version=1)
payload_registry.register(EVIDENCE_CLASS_CHANGED, EvidenceClassChanged, version=1)
