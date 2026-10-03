from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.db.models import Actor, RecruitingActionStatus
from app.state_machines.errors import ActorNotAllowed, InvalidTransition, SnoozeNotInFuture


class RecruitingActionCommand(StrEnum):
    SNOOZE = "snooze"
    WAKE = "wake"
    COMPLETE = "complete"
    DISMISS = "dismiss"
    SUPERSEDE = "supersede"
    RESTORE = "restore"


S = RecruitingActionStatus
C = RecruitingActionCommand

Key = tuple[RecruitingActionStatus, RecruitingActionCommand]

TRANSITIONS: dict[Key, RecruitingActionStatus] = {
    (S.OPEN, C.SNOOZE): S.SNOOZED,
    (S.SNOOZED, C.WAKE): S.OPEN,
    (S.OPEN, C.COMPLETE): S.DONE,
    (S.SNOOZED, C.COMPLETE): S.DONE,
    (S.OPEN, C.DISMISS): S.DISMISSED,
    (S.SNOOZED, C.DISMISS): S.DISMISSED,
    (S.OPEN, C.SUPERSEDE): S.SUPERSEDED,
    (S.SNOOZED, C.SUPERSEDE): S.SUPERSEDED,
    (S.SUPERSEDED, C.RESTORE): S.OPEN,
}

SYSTEM_ONLY = frozenset({C.WAKE, C.SUPERSEDE, C.RESTORE})


@dataclass(frozen=True)
class RecruitingActionTransition:
    new_status: RecruitingActionStatus
    snoozed_until: datetime | None


def recruiting_action_transition(
    status: RecruitingActionStatus,
    command: RecruitingActionCommand,
    *,
    actor: Actor,
    now: datetime,
    until: datetime | None = None,
) -> RecruitingActionTransition:
    if command in SYSTEM_ONLY and actor is Actor.USER:
        raise ActorNotAllowed(command.value)
    target = TRANSITIONS.get((status, command))
    if target is None:
        raise InvalidTransition(f"{status.value} cannot {command.value}")
    if command is C.SNOOZE and (until is None or until <= now):
        raise SnoozeNotInFuture()
    return RecruitingActionTransition(target, until if command is C.SNOOZE else None)
