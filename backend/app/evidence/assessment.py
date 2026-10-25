from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Literal

from app.db.models import ConfirmationStatus, EngagementType, EvidenceClass

Category = Literal[
    "professional", "academic_research", "project", "learning", "gap", "not_recorded"
]
HeadlineCategory = Literal[
    "professional",
    "academic_research",
    "project",
    "learning",
    "gap",
    "unverified",
    "not_recorded",
]

BLOCKS_GAP = frozenset(
    {EvidenceClass.PROFESSIONAL, EvidenceClass.ACADEMIC_RESEARCH, EvidenceClass.PROJECT}
)
COUNTED_ENGAGEMENTS = frozenset(
    {EngagementType.FULL_TIME, EngagementType.PART_TIME, EngagementType.CONTRACT}
)


@dataclass(frozen=True)
class ClaimFacts:
    evidence_class: EvidenceClass
    engagement_type: EngagementType | None
    status: ConfirmationStatus
    start_date: date | None
    end_date: date | None


@dataclass(frozen=True)
class Badge:
    evidence_class: EvidenceClass
    engagement_type: EngagementType | None
    confirmed: bool
    claim_count: int


@dataclass(frozen=True)
class Headline:
    category: HeadlineCategory
    engagement_type: EngagementType | None


@dataclass(frozen=True)
class Assessment:
    badges: list[Badge]
    categories: list[Category]
    headline: Headline
    latest_end_date: date | None
    is_current: bool


def strength(evidence_class: EvidenceClass, engagement_type: EngagementType | None) -> int:
    if evidence_class is EvidenceClass.PROFESSIONAL:
        if engagement_type in COUNTED_ENGAGEMENTS:
            return 0
        return 1 if engagement_type is EngagementType.INTERNSHIP else 2
    return {
        EvidenceClass.ACADEMIC_RESEARCH: 3,
        EvidenceClass.PROJECT: 4,
        EvidenceClass.LEARNING: 5,
    }[evidence_class]


def assess(claims: Iterable[ClaimFacts], *, marked_gap: bool) -> Assessment:
    live = [claim for claim in claims if claim.status is not ConfirmationStatus.REJECTED]
    groups: dict[tuple[EvidenceClass, EngagementType | None], list[ClaimFacts]] = {}
    for claim in live:
        groups.setdefault((claim.evidence_class, claim.engagement_type), []).append(claim)
    badges = [
        Badge(
            evidence_class=key[0],
            engagement_type=key[1],
            confirmed=any(item.status is ConfirmationStatus.CONFIRMED for item in items),
            claim_count=len(items),
        )
        for key, items in sorted(groups.items(), key=lambda entry: strength(*entry[0]))
    ]
    categories: list[Category] = []
    for badge in badges:
        if badge.evidence_class.value not in categories:
            categories.append(badge.evidence_class.value)
    if marked_gap:
        categories.append("gap")
    if not live and not marked_gap:
        categories.append("not_recorded")
    confirmed = [badge for badge in badges if badge.confirmed]
    best = confirmed[0] if confirmed else None
    headline = _headline(best, has_live=bool(live), marked_gap=marked_gap)
    dated = [claim for claim in live if claim.start_date or claim.end_date]
    ends = [claim.end_date for claim in dated if claim.end_date is not None]
    return Assessment(
        badges=badges,
        categories=categories,
        headline=headline,
        latest_end_date=max(ends) if ends else None,
        is_current=any(claim.end_date is None and claim.start_date is not None for claim in live),
    )


def _headline(best: Badge | None, *, has_live: bool, marked_gap: bool) -> Headline:
    if marked_gap and (best is None or best.evidence_class is EvidenceClass.LEARNING):
        return Headline("gap", None)
    if best is not None:
        return Headline(best.evidence_class.value, best.engagement_type)
    return Headline("unverified" if has_live else "not_recorded", None)
