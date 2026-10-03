import pytest

from app.db.models import ReviewStatus
from app.review.errors import InvalidTransition
from app.review.transitions import ReviewAction, transition

EXPECTED = {
    ReviewAction.CONFIRM: ReviewStatus.CONFIRMED,
    ReviewAction.REJECT: ReviewStatus.REJECTED,
    ReviewAction.EXPIRE: ReviewStatus.EXPIRED,
}


@pytest.mark.parametrize("action", list(ReviewAction))
def test_pending_moves_to_the_matching_terminal_state(action: ReviewAction) -> None:
    assert transition(ReviewStatus.PENDING, action) is EXPECTED[action]


@pytest.mark.parametrize("action", list(ReviewAction))
@pytest.mark.parametrize(
    "status", [status for status in ReviewStatus if status is not ReviewStatus.PENDING]
)
def test_terminal_states_never_transition(status: ReviewStatus, action: ReviewAction) -> None:
    with pytest.raises(InvalidTransition):
        transition(status, action)


def test_every_action_and_status_pair_is_covered() -> None:
    assert set(EXPECTED) == set(ReviewAction)
    assert {status.value for status in ReviewStatus} == {
        "pending",
        "confirmed",
        "rejected",
        "expired",
    }
