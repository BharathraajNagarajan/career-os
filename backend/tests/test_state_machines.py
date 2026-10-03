import ast
import itertools
import random
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.db.models import Actor, ApplicationStage, OpportunityStatus, RecruitingActionStatus
from app.state_machines.application import (
    RECORDABLE,
    STAGE_EFFECT,
    TERMINAL_EVENTS,
    USER_ONLY,
    ApplicationEventType,
    ApplicationState,
    EventRecord,
    Projection,
    RecordEvent,
    Reopen,
    VoidEvent,
    application_command_check,
    application_projection,
    is_voidable,
)
from app.state_machines.errors import (
    ActorNotAllowed,
    AlreadyVoided,
    CannotVoid,
    EventTypeNotAllowed,
    InvalidTransition,
    NotTerminal,
    SnoozeNotInFuture,
    TerminalBeforeReopen,
)
from app.state_machines.opportunity import (
    APPLICATION_SUBMITTED,
    OPPORTUNITY_DECIDED,
    OpportunityCommand,
    allowed_actions,
    opportunity_transition,
)
from app.state_machines.recruiting_action import (
    SYSTEM_ONLY,
    RecruitingActionCommand,
    recruiting_action_transition,
)

S = OpportunityStatus
C = OpportunityCommand
E = ApplicationEventType
T = ApplicationStage
R = RecruitingActionStatus
RC = RecruitingActionCommand

BASE = datetime(2026, 1, 1, tzinfo=UTC)

OPPORTUNITY_EXPECTED = {
    (S.NEW, C.SAVE): S.SAVED,
    (S.NEW, C.SKIP): S.SKIPPED,
    (S.NEW, C.APPLY): S.APPLIED,
    (S.NEW, C.CLOSE): S.CLOSED,
    (S.SAVED, C.SKIP): S.SKIPPED,
    (S.SAVED, C.APPLY): S.APPLIED,
    (S.SAVED, C.CLOSE): S.CLOSED,
    (S.SKIPPED, C.SAVE): S.SAVED,
    (S.SKIPPED, C.APPLY): S.APPLIED,
    (S.SKIPPED, C.CLOSE): S.CLOSED,
    (S.CLOSED, C.APPLY): S.APPLIED,
}


@pytest.mark.parametrize(("status", "command"), list(itertools.product(S, C)))
def test_opportunity_every_pair_is_exact(status: S, command: C) -> None:
    expected = OPPORTUNITY_EXPECTED.get((status, command))
    if expected is None:
        with pytest.raises(InvalidTransition) as raised:
            opportunity_transition(status, command)
        assert raised.value.code == "invalid_transition"
        return
    result = opportunity_transition(status, command)
    assert result.new_status is expected
    assert result.event_types == (
        (OPPORTUNITY_DECIDED, APPLICATION_SUBMITTED)
        if command is C.APPLY
        else (OPPORTUNITY_DECIDED,)
    )


def test_opportunity_allowed_actions_match_the_table() -> None:
    for status in S:
        assert allowed_actions(status) == [
            command for command in C if (status, command) in OPPORTUNITY_EXPECTED
        ]
    assert allowed_actions(S.APPLIED) == []


RECRUITING_EXPECTED = {
    (R.OPEN, RC.SNOOZE): R.SNOOZED,
    (R.SNOOZED, RC.WAKE): R.OPEN,
    (R.OPEN, RC.COMPLETE): R.DONE,
    (R.SNOOZED, RC.COMPLETE): R.DONE,
    (R.OPEN, RC.DISMISS): R.DISMISSED,
    (R.SNOOZED, RC.DISMISS): R.DISMISSED,
    (R.OPEN, RC.SUPERSEDE): R.SUPERSEDED,
    (R.SNOOZED, RC.SUPERSEDE): R.SUPERSEDED,
    (R.SUPERSEDED, RC.RESTORE): R.OPEN,
}
FUTURE = BASE + timedelta(days=1)


@pytest.mark.parametrize(("status", "command"), list(itertools.product(R, RC)))
def test_recruiting_action_every_pair_is_exact(status: R, command: RC) -> None:
    actor = Actor.SYSTEM if command in SYSTEM_ONLY else Actor.USER
    expected = RECRUITING_EXPECTED.get((status, command))
    until = FUTURE if command is RC.SNOOZE else None
    if expected is None:
        with pytest.raises(InvalidTransition):
            recruiting_action_transition(status, command, actor=actor, now=BASE, until=until)
        return
    result = recruiting_action_transition(status, command, actor=actor, now=BASE, until=until)
    assert result.new_status is expected
    assert result.snoozed_until == until


@pytest.mark.parametrize("command", sorted(SYSTEM_ONLY))
@pytest.mark.parametrize("status", list(R))
def test_recruiting_action_user_cannot_run_system_commands(status: R, command: RC) -> None:
    with pytest.raises(ActorNotAllowed):
        recruiting_action_transition(status, command, actor=Actor.USER, now=BASE)


@pytest.mark.parametrize("until", [None, BASE, BASE - timedelta(seconds=1)])
def test_snooze_needs_a_future_time(until: datetime | None) -> None:
    with pytest.raises(SnoozeNotInFuture):
        recruiting_action_transition(R.OPEN, RC.SNOOZE, actor=Actor.USER, now=BASE, until=until)


def test_superseded_is_reversible_and_done_dismissed_are_final() -> None:
    superseded = recruiting_action_transition(
        R.OPEN, RC.SUPERSEDE, actor=Actor.SYSTEM, now=BASE
    ).new_status
    restored = recruiting_action_transition(
        superseded, RC.RESTORE, actor=Actor.SYSTEM, now=BASE
    ).new_status
    assert restored is R.OPEN
    for final in (R.DONE, R.DISMISSED):
        for command in RC:
            with pytest.raises(InvalidTransition):
                recruiting_action_transition(
                    final, command, actor=Actor.SYSTEM, now=BASE, until=FUTURE
                )


def day(offset: int, minutes: int = 0) -> datetime:
    return BASE + timedelta(days=offset, minutes=minutes)


def ev(
    event_type: ApplicationEventType,
    occurred: datetime,
    *,
    recorded: datetime | None = None,
    voids: EventRecord | None = None,
    id: uuid.UUID | None = None,
) -> EventRecord:
    return EventRecord(
        id=id or uuid.uuid4(),
        event_type=event_type,
        occurred_at=occurred,
        recorded_at=recorded or occurred,
        voids_event_id=voids.id if voids else None,
    )


def stage_of(events: list[EventRecord]) -> ApplicationStage:
    return application_projection(events).stage


def test_projection_with_only_a_submission_is_applied() -> None:
    assert application_projection([ev(E.APPLICATION_SUBMITTED, day(0))]) == Projection(
        T.APPLIED, False
    )


@pytest.mark.parametrize(("event_type", "stage"), list(STAGE_EFFECT.items()))
def test_each_stage_bearing_event_sets_its_stage(
    event_type: ApplicationEventType, stage: ApplicationStage
) -> None:
    events = [ev(E.APPLICATION_SUBMITTED, day(0)), ev(event_type, day(1))]
    assert application_projection(events) == Projection(stage, event_type in TERMINAL_EVENTS)


NON_STAGE = sorted(set(E) - set(STAGE_EFFECT) - {E.APPLICATION_REOPENED, E.EVENT_VOIDED})


@pytest.mark.parametrize("event_type", NON_STAGE)
def test_non_stage_events_do_not_move_the_stage(event_type: ApplicationEventType) -> None:
    events = [
        ev(E.APPLICATION_SUBMITTED, day(0)),
        ev(E.ASSESSMENT_RECEIVED, day(1)),
        ev(event_type, day(2)),
    ]
    assert stage_of(events) is T.ASSESSMENT


def test_active_stages_move_in_any_direction() -> None:
    events = [
        ev(E.APPLICATION_SUBMITTED, day(0)),
        ev(E.INTERVIEW_COMPLETED, day(1)),
        ev(E.ASSESSMENT_RECEIVED, day(2)),
    ]
    assert stage_of(events) is T.ASSESSMENT


def test_backdated_event_does_not_override_a_later_stage() -> None:
    submitted = ev(E.APPLICATION_SUBMITTED, day(0))
    interviewing = ev(E.INTERVIEW_SCHEDULED, day(10))
    backdated = ev(E.ASSESSMENT_RECEIVED, day(3), recorded=day(20))
    assert stage_of([submitted, interviewing, backdated]) is T.INTERVIEWING


def test_projection_ignores_insertion_order() -> None:
    events = [
        ev(E.APPLICATION_SUBMITTED, day(0)),
        ev(E.ASSESSMENT_RECEIVED, day(1)),
        ev(E.INTERVIEW_REQUESTED, day(2)),
        ev(E.REJECTED, day(5)),
        ev(E.APPLICATION_REOPENED, day(6)),
        ev(E.OFFER_RECEIVED, day(7)),
    ]
    expected = application_projection(events)
    assert expected == Projection(T.OFFER, False)
    generator = random.Random(7)
    for _ in range(50):
        shuffled = events[:]
        generator.shuffle(shuffled)
        assert application_projection(shuffled) == expected


def test_ties_break_by_recorded_at_then_id() -> None:
    low, high = sorted([uuid.uuid4(), uuid.uuid4()])
    submitted = ev(E.APPLICATION_SUBMITTED, day(0))
    first = ev(E.ASSESSMENT_RECEIVED, day(1), recorded=day(2))
    second = ev(E.INTERVIEW_REQUESTED, day(1), recorded=day(3))
    assert stage_of([submitted, second, first]) is T.INTERVIEWING
    same_a = ev(E.ASSESSMENT_RECEIVED, day(1), recorded=day(2), id=low)
    same_b = ev(E.OFFER_RECEIVED, day(1), recorded=day(2), id=high)
    assert stage_of([submitted, same_a, same_b]) is T.OFFER
    assert stage_of([submitted, same_b, same_a]) is T.OFFER


def test_terminal_event_freezes_the_stage() -> None:
    events = [
        ev(E.APPLICATION_SUBMITTED, day(0)),
        ev(E.REJECTED, day(2)),
        ev(E.INTERVIEW_SCHEDULED, day(3)),
    ]
    assert application_projection(events) == Projection(T.REJECTED, True)


def test_a_backdated_stage_before_a_terminal_still_leaves_it_frozen() -> None:
    events = [
        ev(E.APPLICATION_SUBMITTED, day(0)),
        ev(E.REJECTED, day(5)),
        ev(E.OFFER_RECEIVED, day(2), recorded=day(9)),
    ]
    assert application_projection(events) == Projection(T.REJECTED, True)


def test_voiding_a_terminal_event_restores_the_previous_stage() -> None:
    interviewing = ev(E.INTERVIEW_SCHEDULED, day(1))
    rejected = ev(E.REJECTED, day(3))
    events = [ev(E.APPLICATION_SUBMITTED, day(0)), interviewing, rejected]
    assert application_projection(events).is_terminal
    events.append(ev(E.EVENT_VOIDED, day(4), voids=rejected))
    assert application_projection(events) == Projection(T.INTERVIEWING, False)


def test_voided_stage_event_no_longer_counts() -> None:
    assessment = ev(E.ASSESSMENT_RECEIVED, day(1))
    events = [
        ev(E.APPLICATION_SUBMITTED, day(0)),
        assessment,
        ev(E.EVENT_VOIDED, day(2), voids=assessment),
    ]
    assert stage_of(events) is T.APPLIED


def test_reopen_ignores_earlier_terminal_and_recomputes_from_the_rest() -> None:
    events = [
        ev(E.APPLICATION_SUBMITTED, day(0)),
        ev(E.INTERVIEW_SCHEDULED, day(1)),
        ev(E.REJECTED, day(3)),
        ev(E.APPLICATION_REOPENED, day(4)),
    ]
    assert application_projection(events) == Projection(T.INTERVIEWING, False)


def test_reopen_with_no_other_stage_returns_to_applied() -> None:
    events = [
        ev(E.APPLICATION_SUBMITTED, day(0)),
        ev(E.WITHDRAWN, day(1)),
        ev(E.APPLICATION_REOPENED, day(2)),
    ]
    assert application_projection(events) == Projection(T.APPLIED, False)


def test_reopen_followed_by_new_stages_and_a_new_terminal() -> None:
    events = [
        ev(E.APPLICATION_SUBMITTED, day(0)),
        ev(E.REJECTED, day(1)),
        ev(E.APPLICATION_REOPENED, day(2)),
        ev(E.ASSESSMENT_RECEIVED, day(3)),
    ]
    assert stage_of(events) is T.ASSESSMENT
    events.append(ev(E.OFFER_DECLINED, day(4)))
    assert application_projection(events) == Projection(T.DECLINED, True)


def test_voiding_a_reopen_refreezes_the_earlier_terminal() -> None:
    reopen = ev(E.APPLICATION_REOPENED, day(2))
    events = [
        ev(E.APPLICATION_SUBMITTED, day(0)),
        ev(E.REJECTED, day(1)),
        reopen,
    ]
    assert not application_projection(events).is_terminal
    events.append(ev(E.EVENT_VOIDED, day(3), voids=reopen))
    assert application_projection(events) == Projection(T.REJECTED, True)


def test_only_the_latest_reopen_defines_which_terminals_count() -> None:
    events = [
        ev(E.APPLICATION_SUBMITTED, day(0)),
        ev(E.REJECTED, day(1)),
        ev(E.APPLICATION_REOPENED, day(2)),
        ev(E.WITHDRAWN, day(3)),
        ev(E.APPLICATION_REOPENED, day(4)),
    ]
    assert application_projection(events) == Projection(T.APPLIED, False)


def test_a_second_terminal_after_the_first_does_not_change_the_frozen_stage() -> None:
    events = [
        ev(E.APPLICATION_SUBMITTED, day(0)),
        ev(E.REJECTED, day(1)),
        ev(E.WITHDRAWN, day(2)),
    ]
    assert stage_of(events) is T.REJECTED


def state(*events: EventRecord) -> ApplicationState:
    return ApplicationState(list(events))


def open_state() -> ApplicationState:
    return state(ev(E.APPLICATION_SUBMITTED, day(0)), ev(E.ASSESSMENT_RECEIVED, day(1)))


def terminal_state() -> ApplicationState:
    return state(ev(E.APPLICATION_SUBMITTED, day(0)), ev(E.REJECTED, day(1)))


@pytest.mark.parametrize("event_type", list(E))
@pytest.mark.parametrize("actor", list(Actor))
@pytest.mark.parametrize("terminal", [False, True])
def test_record_event_every_type_actor_and_state(
    event_type: ApplicationEventType, actor: Actor, terminal: bool
) -> None:
    current = terminal_state() if terminal else open_state()
    command = RecordEvent(event_type, day(5))
    if event_type not in RECORDABLE:
        with pytest.raises(EventTypeNotAllowed):
            application_command_check(current, command, actor=actor)
    elif actor is not Actor.USER and event_type in USER_ONLY:
        with pytest.raises(ActorNotAllowed):
            application_command_check(current, command, actor=actor)
    elif terminal and event_type in TERMINAL_EVENTS:
        with pytest.raises(InvalidTransition):
            application_command_check(current, command, actor=actor)
    else:
        assert application_command_check(current, command, actor=actor) == (event_type,)


def test_system_and_gmail_may_record_rejection_but_never_no_response() -> None:
    for actor in (Actor.SYSTEM, Actor.GMAIL):
        assert application_command_check(
            open_state(), RecordEvent(E.REJECTED, day(5)), actor=actor
        ) == (E.REJECTED,)
        with pytest.raises(ActorNotAllowed):
            application_command_check(
                open_state(), RecordEvent(E.MARKED_NO_RESPONSE, day(5)), actor=actor
            )


def test_terminal_event_before_the_latest_reopen_is_refused() -> None:
    current = state(
        ev(E.APPLICATION_SUBMITTED, day(0)),
        ev(E.REJECTED, day(1)),
        ev(E.APPLICATION_REOPENED, day(5)),
    )
    with pytest.raises(TerminalBeforeReopen):
        application_command_check(current, RecordEvent(E.WITHDRAWN, day(4)), actor=Actor.USER)
    assert application_command_check(
        current, RecordEvent(E.WITHDRAWN, day(6)), actor=Actor.USER
    ) == (E.WITHDRAWN,)
    assert application_command_check(
        current, RecordEvent(E.ASSESSMENT_RECEIVED, day(4)), actor=Actor.USER
    ) == (E.ASSESSMENT_RECEIVED,)


def test_void_rules() -> None:
    submitted = ev(E.APPLICATION_SUBMITTED, day(0))
    assessment = ev(E.ASSESSMENT_RECEIVED, day(1))
    note = ev(E.NOTE_ADDED, day(2))
    voiding = ev(E.EVENT_VOIDED, day(3), voids=note)
    current = state(submitted, assessment, note, voiding)

    assert application_command_check(current, VoidEvent(assessment.id), actor=Actor.USER) == (
        E.EVENT_VOIDED,
    )
    with pytest.raises(CannotVoid):
        application_command_check(current, VoidEvent(submitted.id), actor=Actor.USER)
    with pytest.raises(CannotVoid):
        application_command_check(current, VoidEvent(voiding.id), actor=Actor.USER)
    with pytest.raises(AlreadyVoided):
        application_command_check(current, VoidEvent(note.id), actor=Actor.USER)
    with pytest.raises(CannotVoid):
        application_command_check(current, VoidEvent(uuid.uuid4()), actor=Actor.USER)
    with pytest.raises(ActorNotAllowed):
        application_command_check(current, VoidEvent(assessment.id), actor=Actor.SYSTEM)


def test_a_reopen_can_be_voided() -> None:
    reopen = ev(E.APPLICATION_REOPENED, day(2))
    current = state(ev(E.APPLICATION_SUBMITTED, day(0)), ev(E.REJECTED, day(1)), reopen)
    assert application_command_check(current, VoidEvent(reopen.id), actor=Actor.USER) == (
        E.EVENT_VOIDED,
    )


def test_voidable_flag_matches_the_void_rules() -> None:
    submitted = ev(E.APPLICATION_SUBMITTED, day(0))
    note = ev(E.NOTE_ADDED, day(1))
    other = ev(E.OFFER_RECEIVED, day(2))
    voiding = ev(E.EVENT_VOIDED, day(3), voids=note)
    current = state(submitted, note, other, voiding)
    assert [is_voidable(current, item) for item in (submitted, note, other, voiding)] == [
        False,
        False,
        True,
        False,
    ]


@pytest.mark.parametrize("actor", list(Actor))
def test_reopen_every_state_and_actor(actor: Actor) -> None:
    if actor is not Actor.USER:
        with pytest.raises(ActorNotAllowed):
            application_command_check(terminal_state(), Reopen(), actor=actor)
        return
    assert application_command_check(terminal_state(), Reopen(), actor=actor) == (
        E.APPLICATION_REOPENED,
    )
    with pytest.raises(NotTerminal):
        application_command_check(open_state(), Reopen(), actor=actor)


def test_reopen_refused_when_the_terminal_event_was_voided() -> None:
    rejected = ev(E.REJECTED, day(1))
    current = state(
        ev(E.APPLICATION_SUBMITTED, day(0)), rejected, ev(E.EVENT_VOIDED, day(2), voids=rejected)
    )
    with pytest.raises(NotTerminal):
        application_command_check(current, Reopen(), actor=Actor.USER)


def test_typed_errors_have_stable_codes_and_statuses() -> None:
    codes = {
        InvalidTransition: (409, "invalid_transition"),
        CannotVoid: (409, "cannot_void"),
        AlreadyVoided: (409, "already_voided"),
        NotTerminal: (409, "not_terminal"),
        EventTypeNotAllowed: (422, "event_type_not_allowed"),
        SnoozeNotInFuture: (422, "snooze_not_in_future"),
    }
    for error, (status, code) in codes.items():
        assert (error.status_code, error.code) == (status, code)


def test_state_machine_modules_stay_pure() -> None:
    root = Path(__file__).resolve().parents[1] / "app" / "state_machines"
    allowed_models = {
        "Actor",
        "ApplicationStage",
        "OpportunityStatus",
        "RecruitingActionStatus",
        "TERMINAL_STAGES",
    }
    for path in sorted(root.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
                if node.module == "app.db.models":
                    assert {alias.name for alias in node.names} <= allowed_models, path.name
            else:
                continue
            for module in modules:
                top = module.split(".")[0]
                assert top in {"app", "uuid", "collections", "dataclasses", "datetime", "enum"}
                assert not module.startswith(("app.core", "app.auth", "app.events", "app.jobs"))
