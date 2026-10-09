from datetime import UTC, datetime, timedelta

from app.db.models import Actor, RecruitingActionStatus
from app.state_machines.errors import TransitionError
from app.state_machines.recruiting_action import (
    RecruitingActionCommand,
    recruiting_action_transition,
)

USER_COMMANDS = (
    RecruitingActionCommand.SNOOZE,
    RecruitingActionCommand.COMPLETE,
    RecruitingActionCommand.DISMISS,
)


def allowed_user_commands(status: RecruitingActionStatus) -> list[RecruitingActionCommand]:
    now = datetime.now(UTC)
    allowed: list[RecruitingActionCommand] = []
    for command in USER_COMMANDS:
        try:
            recruiting_action_transition(
                status, command, actor=Actor.USER, now=now, until=now + timedelta(days=1)
            )
        except TransitionError:
            continue
        allowed.append(command)
    return allowed
