import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.db.models import TERMINAL_STAGES, Actor, ApplicationStage
from app.state_machines.errors import (
    ActorNotAllowed,
    AlreadyVoided,
    CannotVoid,
    EventTypeNotAllowed,
    InvalidTransition,
    NotTerminal,
    TerminalBeforeReopen,
)


class ApplicationEventType(StrEnum):
    APPLICATION_SUBMITTED = "APPLICATION_SUBMITTED"
    APPLICATION_ACKNOWLEDGED = "APPLICATION_ACKNOWLEDGED"
    ASSESSMENT_RECEIVED = "ASSESSMENT_RECEIVED"
    ASSESSMENT_COMPLETED = "ASSESSMENT_COMPLETED"
    INTERVIEW_REQUESTED = "INTERVIEW_REQUESTED"
    INTERVIEW_SCHEDULED = "INTERVIEW_SCHEDULED"
    INTERVIEW_COMPLETED = "INTERVIEW_COMPLETED"
    OFFER_RECEIVED = "OFFER_RECEIVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    OFFER_ACCEPTED = "OFFER_ACCEPTED"
    OFFER_DECLINED = "OFFER_DECLINED"
    MARKED_NO_RESPONSE = "MARKED_NO_RESPONSE"
    CONNECTION_REQUEST_SENT = "CONNECTION_REQUEST_SENT"
    CONNECTION_ACCEPTED = "CONNECTION_ACCEPTED"
    OUTREACH_SENT = "OUTREACH_SENT"
    FOLLOWUP_SENT = "FOLLOWUP_SENT"
    RECRUITER_CONTACTED = "RECRUITER_CONTACTED"
    CONTACT_REPLIED = "CONTACT_REPLIED"
    NOTE_ADDED = "NOTE_ADDED"
    APPLICATION_REOPENED = "APPLICATION_REOPENED"
    EVENT_VOIDED = "EVENT_VOIDED"


E = ApplicationEventType
T = ApplicationStage

STAGE_EFFECT: dict[ApplicationEventType, ApplicationStage] = {
    E.APPLICATION_SUBMITTED: T.APPLIED,
    E.ASSESSMENT_RECEIVED: T.ASSESSMENT,
    E.ASSESSMENT_COMPLETED: T.ASSESSMENT,
    E.INTERVIEW_REQUESTED: T.INTERVIEWING,
    E.INTERVIEW_SCHEDULED: T.INTERVIEWING,
    E.INTERVIEW_COMPLETED: T.INTERVIEWING,
    E.OFFER_RECEIVED: T.OFFER,
    E.REJECTED: T.REJECTED,
    E.WITHDRAWN: T.WITHDRAWN,
    E.OFFER_ACCEPTED: T.ACCEPTED,
    E.OFFER_DECLINED: T.DECLINED,
    E.MARKED_NO_RESPONSE: T.NO_RESPONSE,
}

OWN_COMMAND_ONLY = frozenset({E.APPLICATION_SUBMITTED, E.APPLICATION_REOPENED, E.EVENT_VOIDED})
RECORDABLE = frozenset(E) - OWN_COMMAND_ONLY
USER_ONLY = frozenset(
    {E.WITHDRAWN, E.OFFER_ACCEPTED, E.OFFER_DECLINED, E.MARKED_NO_RESPONSE} | OWN_COMMAND_ONLY
)
TERMINAL_EVENTS = frozenset(
    event for event, stage in STAGE_EFFECT.items() if stage in TERMINAL_STAGES
)


@dataclass(frozen=True)
class EventRecord:
    id: uuid.UUID
    event_type: ApplicationEventType
    occurred_at: datetime
    recorded_at: datetime
    voids_event_id: uuid.UUID | None = None

    @property
    def order_key(self) -> tuple[datetime, datetime, uuid.UUID]:
        return (self.occurred_at, self.recorded_at, self.id)


@dataclass(frozen=True)
class Projection:
    stage: ApplicationStage
    is_terminal: bool


@dataclass(frozen=True)
class ApplicationState:
    events: Sequence[EventRecord]

    @property
    def projection(self) -> Projection:
        return application_projection(self.events)


@dataclass(frozen=True)
class RecordEvent:
    event_type: ApplicationEventType
    occurred_at: datetime


@dataclass(frozen=True)
class VoidEvent:
    event_id: uuid.UUID


@dataclass(frozen=True)
class Reopen:
    pass


ApplicationCommand = RecordEvent | VoidEvent | Reopen


def ordered(events: Iterable[EventRecord]) -> list[EventRecord]:
    return sorted(events, key=lambda event: event.order_key)


def voided_ids(events: Iterable[EventRecord]) -> set[uuid.UUID]:
    return {
        event.voids_event_id
        for event in events
        if event.event_type is E.EVENT_VOIDED and event.voids_event_id is not None
    }


def live_events(events: Iterable[EventRecord]) -> list[EventRecord]:
    items = list(events)
    gone = voided_ids(items)
    return [
        event
        for event in ordered(items)
        if event.id not in gone and event.event_type is not E.EVENT_VOIDED
    ]


def latest_reopen(live: Iterable[EventRecord]) -> EventRecord | None:
    reopens = [event for event in live if event.event_type is E.APPLICATION_REOPENED]
    return reopens[-1] if reopens else None


def application_projection(events: Iterable[EventRecord]) -> Projection:
    live = live_events(events)
    reopen = latest_reopen(live)
    stage = T.APPLIED
    for event in live:
        effect = STAGE_EFFECT.get(event.event_type)
        if effect is None:
            continue
        if (
            reopen is not None
            and event.event_type in TERMINAL_EVENTS
            and event.order_key <= reopen.order_key
        ):
            continue
        stage = effect
        if effect in TERMINAL_STAGES:
            break
    return Projection(stage, stage in TERMINAL_STAGES)


def is_voidable(state: ApplicationState, event: EventRecord) -> bool:
    return event.event_type not in {E.APPLICATION_SUBMITTED, E.EVENT_VOIDED} and (
        event.id not in voided_ids(state.events)
    )


def application_command_check(
    state: ApplicationState, command: ApplicationCommand, *, actor: Actor
) -> tuple[ApplicationEventType, ...]:
    if isinstance(command, RecordEvent):
        return _check_record(state, command, actor)
    if isinstance(command, VoidEvent):
        return _check_void(state, command, actor)
    return _check_reopen(state, actor)


def _check_record(
    state: ApplicationState, command: RecordEvent, actor: Actor
) -> tuple[ApplicationEventType, ...]:
    event_type = command.event_type
    if event_type not in RECORDABLE:
        raise EventTypeNotAllowed(event_type.value)
    if actor is not Actor.USER and event_type in USER_ONLY:
        raise ActorNotAllowed(event_type.value)
    if event_type in TERMINAL_EVENTS:
        projection = state.projection
        if projection.is_terminal:
            raise InvalidTransition(f"application is {projection.stage.value}")
        reopen = latest_reopen(live_events(state.events))
        if reopen is not None and command.occurred_at < reopen.occurred_at:
            raise TerminalBeforeReopen()
    return (event_type,)


def _check_void(
    state: ApplicationState, command: VoidEvent, actor: Actor
) -> tuple[ApplicationEventType, ...]:
    if actor is not Actor.USER:
        raise ActorNotAllowed(E.EVENT_VOIDED.value)
    target = next((event for event in state.events if event.id == command.event_id), None)
    if target is None:
        raise CannotVoid("not_on_application")
    if target.event_type is E.APPLICATION_SUBMITTED:
        raise CannotVoid("submission")
    if target.event_type is E.EVENT_VOIDED:
        raise CannotVoid("void")
    if target.id in voided_ids(state.events):
        raise AlreadyVoided()
    return (E.EVENT_VOIDED,)


def _check_reopen(state: ApplicationState, actor: Actor) -> tuple[ApplicationEventType, ...]:
    if actor is not Actor.USER:
        raise ActorNotAllowed(E.APPLICATION_REOPENED.value)
    if not state.projection.is_terminal:
        raise NotTerminal()
    return (E.APPLICATION_REOPENED,)
