import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import cast

from sqlalchemy import Table, func
from sqlalchemy.orm import Session

from app.actions.events import (
    ACTION_CREATED,
    ACTION_EDITED,
    TRANSITION_EVENTS,
    RecruitingActionCreated,
    RecruitingActionEdited,
    RecruitingActionTransitioned,
)
from app.actions.jobs import WAKE_ACTION_JOB, WakeActionPayload, wake_unique_key
from app.actions.repository import RecruitingActionRepository
from app.applications.service import run_in_transaction
from app.core.errors import ApiError
from app.db.clock import database_now
from app.db.models import (
    ActionOrigin,
    Actor,
    AggregateType,
    Application,
    Contact,
    Interaction,
    Opportunity,
    RecruitingAction,
    RecruitingActionKind,
    RecruitingActionStatus,
)
from app.db.tenancy import resolve_owned
from app.db.versioning import ConcurrencyConflict, update_versioned
from app.events.repository import DomainEventRepository
from app.jobs.queue import enqueue
from app.state_machines.errors import InvalidTransition
from app.state_machines.recruiting_action import (
    RecruitingActionCommand,
    recruiting_action_transition,
)

SCHEDULED_KINDS = frozenset(
    {RecruitingActionKind.ATTEND_INTERVIEW, RecruitingActionKind.COMPLETE_ASSESSMENT}
)
EDITABLE_STATUSES = frozenset({RecruitingActionStatus.OPEN, RecruitingActionStatus.SNOOZED})


class ActionService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.actions = RecruitingActionRepository(session)
        self.events = DomainEventRepository(session)

    def list_for_user(
        self,
        *,
        user_id: uuid.UUID,
        statuses: Sequence[RecruitingActionStatus] | None,
        kind: RecruitingActionKind | None,
        opportunity_id: uuid.UUID | None,
        application_id: uuid.UUID | None,
        contact_id: uuid.UUID | None,
    ) -> Sequence[RecruitingAction]:
        return self.actions.list_filtered(
            user_id=user_id,
            statuses=statuses,
            kind=kind,
            opportunity_id=opportunity_id,
            application_id=application_id,
            contact_id=contact_id,
        )

    def get(self, *, user_id: uuid.UUID, action_id: uuid.UUID) -> RecruitingAction:
        return self.actions.get(user_id=user_id, id=action_id)

    def create(
        self,
        *,
        user_id: uuid.UUID,
        kind: RecruitingActionKind,
        title: str,
        due_at: datetime | None,
        opportunity_id: uuid.UUID | None,
        application_id: uuid.UUID | None,
        contact_id: uuid.UUID | None,
        interaction_id: uuid.UUID | None,
    ) -> RecruitingAction:
        if kind is RecruitingActionKind.OUTREACH:
            raise ApiError(422, "kind_not_creatable")
        if kind in SCHEDULED_KINDS and due_at is None:
            raise ApiError(422, "due_at_required")

        def work() -> RecruitingAction:
            linked_opportunity = self._resolve_links(
                user_id, opportunity_id, application_id, contact_id, interaction_id
            )
            row = RecruitingAction(
                user_id=user_id,
                kind=kind,
                title=title,
                due_at=due_at,
                status=RecruitingActionStatus.OPEN,
                sequence_no=self._sequence_no(
                    user_id, kind, application_id, linked_opportunity, contact_id
                ),
                opportunity_id=linked_opportunity,
                application_id=application_id,
                contact_id=contact_id,
                interaction_id=interaction_id,
                origin=ActionOrigin.USER,
            )
            self.session.add(row)
            self.session.flush()
            self.events.append(
                user_id=user_id,
                aggregate_type=AggregateType.RECRUITING_ACTION,
                aggregate_id=row.id,
                event_type=ACTION_CREATED,
                occurred_at=database_now(self.session),
                actor=Actor.USER,
                payload=RecruitingActionCreated(
                    action_id=row.id,
                    kind=kind.value,
                    origin=ActionOrigin.USER.value,
                    due_at=due_at,
                    opportunity_id=linked_opportunity,
                    application_id=application_id,
                    contact_id=contact_id,
                    interaction_id=interaction_id,
                ),
            )
            return row

        return run_in_transaction(self.session, work, commit=True)

    def edit(
        self,
        *,
        user_id: uuid.UUID,
        action_id: uuid.UUID,
        expected_state_version: int,
        title: str | None,
        due_at: datetime | None,
        set_due_at: bool,
    ) -> RecruitingAction:
        def work() -> RecruitingAction:
            row = self._lock(user_id, action_id, expected_state_version)
            if row.status not in EDITABLE_STATUSES:
                raise InvalidTransition(f"{row.status.value} cannot be edited")
            changed: list[str] = []
            if title is not None and title != row.title:
                row.title = title
                changed.append("title")
            if set_due_at and due_at != row.due_at:
                if due_at is None and row.kind in SCHEDULED_KINDS:
                    raise ApiError(422, "due_at_required")
                row.due_at = due_at
                changed.append("due_at")
            if changed:
                self.session.flush()
                self.events.append(
                    user_id=user_id,
                    aggregate_type=AggregateType.RECRUITING_ACTION,
                    aggregate_id=row.id,
                    event_type=ACTION_EDITED,
                    occurred_at=database_now(self.session),
                    actor=Actor.USER,
                    payload=RecruitingActionEdited(action_id=row.id, fields=changed),
                )
            return row

        return run_in_transaction(self.session, work, commit=True)

    def transition(
        self,
        *,
        user_id: uuid.UUID,
        action_id: uuid.UUID,
        command: RecruitingActionCommand,
        expected_state_version: int,
        actor: Actor = Actor.USER,
        until: datetime | None = None,
        commit: bool = True,
    ) -> RecruitingAction:
        def work() -> RecruitingAction:
            row = self._lock(user_id, action_id, expected_state_version)
            now = database_now(self.session)
            result = recruiting_action_transition(
                row.status, command, actor=actor, now=now, until=until
            )
            from_status = row.status
            new_version = update_versioned(
                self.session,
                cast(Table, RecruitingAction.__table__),
                user_id=user_id,
                id=row.id,
                expected_version=row.state_version,
                values={
                    "status": result.new_status,
                    "snoozed_until": result.snoozed_until,
                    "updated_at": func.now(),
                },
            )
            self.events.append(
                user_id=user_id,
                aggregate_type=AggregateType.RECRUITING_ACTION,
                aggregate_id=row.id,
                event_type=TRANSITION_EVENTS[command],
                occurred_at=now,
                actor=actor,
                payload=RecruitingActionTransitioned(
                    action_id=row.id,
                    from_status=from_status.value,
                    to_status=result.new_status.value,
                    snoozed_until=result.snoozed_until,
                ),
            )
            if result.snoozed_until is not None:
                enqueue(
                    self.session,
                    kind=WAKE_ACTION_JOB,
                    payload=WakeActionPayload(action_id=row.id, state_version=new_version),
                    user_id=user_id,
                    unique_key=wake_unique_key(row.id, new_version),
                    run_after=result.snoozed_until,
                )
            self.session.expire_all()
            return self.actions.get(user_id=user_id, id=action_id)

        return run_in_transaction(self.session, work, commit=commit)

    def wake_if_current(
        self, *, user_id: uuid.UUID, action_id: uuid.UUID, state_version: int
    ) -> bool:
        row = self.actions.lock(user_id=user_id, id=action_id)
        if row.status is not RecruitingActionStatus.SNOOZED or row.state_version != state_version:
            return False
        self.transition(
            user_id=user_id,
            action_id=action_id,
            command=RecruitingActionCommand.WAKE,
            expected_state_version=state_version,
            actor=Actor.SYSTEM,
            commit=False,
        )
        return True

    def _lock(self, user_id: uuid.UUID, action_id: uuid.UUID, expected: int) -> RecruitingAction:
        row = self.actions.lock(user_id=user_id, id=action_id)
        if row.state_version != expected:
            raise ConcurrencyConflict("recruiting_actions")
        return row

    def _resolve_links(
        self,
        user_id: uuid.UUID,
        opportunity_id: uuid.UUID | None,
        application_id: uuid.UUID | None,
        contact_id: uuid.UUID | None,
        interaction_id: uuid.UUID | None,
    ) -> uuid.UUID | None:
        linked_opportunity = opportunity_id
        if opportunity_id is not None:
            resolve_owned(self.session, Opportunity, user_id=user_id, id=opportunity_id)
        if application_id is not None:
            application = resolve_owned(
                self.session, Application, user_id=user_id, id=application_id
            )
            if opportunity_id is not None and application.opportunity_id != opportunity_id:
                raise ApiError(422, "application_opportunity_mismatch")
            linked_opportunity = application.opportunity_id
        if contact_id is not None:
            resolve_owned(self.session, Contact, user_id=user_id, id=contact_id)
        if interaction_id is not None:
            resolve_owned(self.session, Interaction, user_id=user_id, id=interaction_id)
        return linked_opportunity

    def _sequence_no(
        self,
        user_id: uuid.UUID,
        kind: RecruitingActionKind,
        application_id: uuid.UUID | None,
        opportunity_id: uuid.UUID | None,
        contact_id: uuid.UUID | None,
    ) -> int:
        if kind is not RecruitingActionKind.FOLLOW_UP:
            return 1
        if application_id is None and opportunity_id is None and contact_id is None:
            return 1
        return 1 + self.actions.count_follow_ups(
            user_id=user_id,
            application_id=application_id,
            opportunity_id=opportunity_id,
            contact_id=contact_id,
        )
