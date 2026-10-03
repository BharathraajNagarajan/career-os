from dataclasses import dataclass
from enum import StrEnum

from app.db.models import OpportunityStatus
from app.state_machines.errors import InvalidTransition

OPPORTUNITY_DECIDED = "OPPORTUNITY_DECIDED"
APPLICATION_SUBMITTED = "APPLICATION_SUBMITTED"


class OpportunityCommand(StrEnum):
    SAVE = "save"
    SKIP = "skip"
    APPLY = "apply"
    CLOSE = "close"


S = OpportunityStatus
C = OpportunityCommand

TRANSITIONS: dict[tuple[OpportunityStatus, OpportunityCommand], OpportunityStatus] = {
    (S.NEW, C.SAVE): S.SAVED,
    (S.SKIPPED, C.SAVE): S.SAVED,
    (S.NEW, C.SKIP): S.SKIPPED,
    (S.SAVED, C.SKIP): S.SKIPPED,
    (S.NEW, C.CLOSE): S.CLOSED,
    (S.SAVED, C.CLOSE): S.CLOSED,
    (S.SKIPPED, C.CLOSE): S.CLOSED,
    (S.NEW, C.APPLY): S.APPLIED,
    (S.SAVED, C.APPLY): S.APPLIED,
    (S.SKIPPED, C.APPLY): S.APPLIED,
    (S.CLOSED, C.APPLY): S.APPLIED,
}


@dataclass(frozen=True)
class OpportunityTransition:
    new_status: OpportunityStatus
    event_types: tuple[str, ...]


def opportunity_transition(
    status: OpportunityStatus, command: OpportunityCommand
) -> OpportunityTransition:
    target = TRANSITIONS.get((status, command))
    if target is None:
        raise InvalidTransition(f"{status.value} cannot {command.value}")
    events = (
        (OPPORTUNITY_DECIDED, APPLICATION_SUBMITTED)
        if command is OpportunityCommand.APPLY
        else (OPPORTUNITY_DECIDED,)
    )
    return OpportunityTransition(target, events)


def allowed_actions(status: OpportunityStatus) -> list[OpportunityCommand]:
    return [command for command in OpportunityCommand if (status, command) in TRANSITIONS]
