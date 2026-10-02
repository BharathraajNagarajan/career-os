from enum import StrEnum

from app.db.models import ReviewStatus
from app.review.errors import InvalidTransition


class ReviewAction(StrEnum):
    CONFIRM = "confirm"
    REJECT = "reject"
    EXPIRE = "expire"


_TARGETS = {
    ReviewAction.CONFIRM: ReviewStatus.CONFIRMED,
    ReviewAction.REJECT: ReviewStatus.REJECTED,
    ReviewAction.EXPIRE: ReviewStatus.EXPIRED,
}


def transition(current: ReviewStatus, action: ReviewAction) -> ReviewStatus:
    if current is not ReviewStatus.PENDING:
        raise InvalidTransition(f"{current.value} cannot {action.value}")
    return _TARGETS[action]
