from difflib import SequenceMatcher

from app.db.models import Opportunity
from app.opportunities.normalize import normalize_text
from app.opportunities.schemas import Reason

TITLE_SIMILARITY_THRESHOLD = 0.9


def duplicate_reason(subject: Opportunity, other: Opportunity) -> tuple[Reason, float] | None:
    if subject.company_id is None or subject.company_id != other.company_id:
        return None
    if subject.external_job_id and subject.external_job_id == other.external_job_id:
        return "exact_job_id", 1.0
    if not subject.title or not other.title:
        return None
    similarity = SequenceMatcher(
        None, normalize_text(subject.title), normalize_text(other.title)
    ).ratio()
    if similarity < TITLE_SIMILARITY_THRESHOLD:
        return None
    subject_location = normalize_text(subject.location_text or "")
    other_location = normalize_text(other.location_text or "")
    if subject_location and other_location and subject_location != other_location:
        return None
    return "similar_title", round(similarity, 3)
