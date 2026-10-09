import uuid
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.applications.events import ApplicationEventVoided, ApplicationNoted, ApplicationSubmitted
from app.applications.repository import ApplicationRepository, ApplicationRow, event_record
from app.core.errors import ApiError
from app.db.clock import database_now
from app.db.models import (
    Actor,
    AggregateType,
    Application,
    ApplicationChannel,
    ApplicationStage,
)
from app.db.versioning import ConcurrencyConflict
from app.events.repository import DomainEventRepository
from app.state_machines.application import (
    ApplicationEventType,
    ApplicationState,
    RecordEvent,
    Reopen,
    VoidEvent,
    application_command_check,
    application_projection,
)
from app.state_machines.errors import OccurredAtInFuture

FUTURE_TOLERANCE = timedelta(minutes=5)


def run_in_transaction[R](session: Session, work: Callable[[], R], *, commit: bool) -> R:
    try:
        result = work()
        if commit:
            session.commit()
        return result
    except ConcurrencyConflict as exc:
        _abort(session, commit)
        raise ApiError(409, "conflict") from exc
    except IntegrityError as exc:
        _abort(session, commit)
        raise ApiError(409, "conflict") from exc
    except BaseException:
        _abort(session, commit)
        raise


def _abort(session: Session, commit: bool) -> None:
    if commit:
        session.rollback()


def refuse_future(session: Session, moment: datetime) -> None:
    if moment > database_now(session) + FUTURE_TOLERANCE:
        raise OccurredAtInFuture()


class ApplicationService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.applications = ApplicationRepository(session)
        self.events = DomainEventRepository(session)

    def list_for_user(
        self,
        *,
        user_id: uuid.UUID,
        stage: ApplicationStage | None,
        is_terminal: bool | None,
        opportunity_id: uuid.UUID | None,
    ) -> list[ApplicationRow]:
        return list(
            self.applications.list_with_context(
                user_id=user_id, stage=stage, is_terminal=is_terminal, opportunity_id=opportunity_id
            )
        )

    def get(self, *, user_id: uuid.UUID, application_id: uuid.UUID) -> ApplicationRow:
        return self.applications.get_with_context(user_id=user_id, id=application_id)

    def create(
        self,
        *,
        user_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        resume_id: uuid.UUID | None,
        lane_id: uuid.UUID | None,
        channel: ApplicationChannel,
        applied_at: datetime,
        correlation_id: uuid.UUID,
        actor: Actor,
        source_ref_id: uuid.UUID | None,
    ) -> Application:
        row = Application(
            user_id=user_id,
            opportunity_id=opportunity_id,
            resume_id=resume_id,
            lane_id=lane_id,
            applied_at=applied_at,
            channel=channel,
            stage=ApplicationStage.APPLIED,
            is_terminal=False,
        )
        self.session.add(row)
        self.session.flush()
        self.events.append(
            user_id=user_id,
            aggregate_type=AggregateType.APPLICATION,
            aggregate_id=row.id,
            event_type=ApplicationEventType.APPLICATION_SUBMITTED.value,
            occurred_at=applied_at,
            actor=actor,
            payload=ApplicationSubmitted(
                application_id=row.id,
                opportunity_id=opportunity_id,
                resume_id=resume_id,
                lane_id=lane_id,
                channel=channel.value,
            ),
            source_ref_id=source_ref_id,
            correlation_id=correlation_id,
        )
        return row

    def record_event(
        self,
        *,
        user_id: uuid.UUID,
        application_id: uuid.UUID,
        expected_state_version: int,
        event_type: ApplicationEventType,
        occurred_at: datetime,
        note: str | None,
        actor: Actor = Actor.USER,
        source_ref_id: uuid.UUID | None = None,
        interaction_id: uuid.UUID | None = None,
        commit: bool = True,
    ) -> int:
        def work() -> int:
            row = self._lock(user_id, application_id, expected_state_version)
            refuse_future(self.session, occurred_at)
            self._check(user_id, row.id, RecordEvent(event_type, occurred_at), actor)
            self.events.append(
                user_id=user_id,
                aggregate_type=AggregateType.APPLICATION,
                aggregate_id=row.id,
                event_type=event_type.value,
                occurred_at=occurred_at,
                actor=actor,
                payload=ApplicationNoted(
                    application_id=row.id, note=note, interaction_id=interaction_id
                ),
                source_ref_id=source_ref_id,
            )
            return self._reproject(user_id, row)

        return run_in_transaction(self.session, work, commit=commit)

    def void_event(
        self,
        *,
        user_id: uuid.UUID,
        application_id: uuid.UUID,
        expected_state_version: int,
        event_id: uuid.UUID,
        reason: str | None,
        actor: Actor = Actor.USER,
        source_ref_id: uuid.UUID | None = None,
        commit: bool = True,
    ) -> int:
        def work() -> int:
            row = self._lock(user_id, application_id, expected_state_version)
            self.events.get(user_id=user_id, id=event_id)
            self._check(user_id, row.id, VoidEvent(event_id), actor)
            self.events.append(
                user_id=user_id,
                aggregate_type=AggregateType.APPLICATION,
                aggregate_id=row.id,
                event_type=ApplicationEventType.EVENT_VOIDED.value,
                occurred_at=database_now(self.session),
                actor=actor,
                payload=ApplicationEventVoided(
                    application_id=row.id, voided_event_id=event_id, reason=reason
                ),
                source_ref_id=source_ref_id,
                voids_event_id=event_id,
            )
            return self._reproject(user_id, row)

        return run_in_transaction(self.session, work, commit=commit)

    def reopen(
        self,
        *,
        user_id: uuid.UUID,
        application_id: uuid.UUID,
        expected_state_version: int,
        note: str | None,
        actor: Actor = Actor.USER,
        source_ref_id: uuid.UUID | None = None,
        commit: bool = True,
    ) -> int:
        def work() -> int:
            row = self._lock(user_id, application_id, expected_state_version)
            state = self._records(user_id, row.id)
            application_command_check(state, Reopen(), actor=actor)
            reopened_at = max(
                [database_now(self.session), *(event.occurred_at for event in state.events)]
            )
            self.events.append(
                user_id=user_id,
                aggregate_type=AggregateType.APPLICATION,
                aggregate_id=row.id,
                event_type=ApplicationEventType.APPLICATION_REOPENED.value,
                occurred_at=reopened_at,
                actor=actor,
                payload=ApplicationNoted(application_id=row.id, note=note),
                source_ref_id=source_ref_id,
            )
            return self._reproject(user_id, row)

        return run_in_transaction(self.session, work, commit=commit)

    def _lock(self, user_id: uuid.UUID, application_id: uuid.UUID, expected: int) -> Application:
        row = self.applications.lock(user_id=user_id, id=application_id)
        if row.state_version != expected:
            raise ConcurrencyConflict("applications")
        return row

    def _records(self, user_id: uuid.UUID, application_id: uuid.UUID) -> ApplicationState:
        events = self.events.list_for_aggregate(
            user_id=user_id,
            aggregate_type=AggregateType.APPLICATION,
            aggregate_id=application_id,
        )
        return ApplicationState([event_record(event) for event in events])

    def _check(
        self,
        user_id: uuid.UUID,
        application_id: uuid.UUID,
        command: RecordEvent | VoidEvent | Reopen,
        actor: Actor,
    ) -> None:
        application_command_check(self._records(user_id, application_id), command, actor=actor)

    def _reproject(self, user_id: uuid.UUID, row: Application) -> int:
        projection = application_projection(self._records(user_id, row.id).events)
        return self.applications.write_projection(
            user_id=user_id,
            id=row.id,
            expected_version=row.state_version,
            stage=projection.stage,
            is_terminal=projection.is_terminal,
        )
