import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.applications.service import ApplicationService, refuse_future, run_in_transaction
from app.core.errors import ApiError
from app.core.ids import new_id
from app.db.clock import database_now
from app.db.models import (
    Actor,
    AggregateType,
    Application,
    ApplicationChannel,
    LaneStatus,
    Opportunity,
    OpportunityStatus,
    ResumeStatus,
)
from app.db.versioning import ConcurrencyConflict
from app.events.repository import DomainEventRepository
from app.opportunities.events import OpportunityDecided
from app.opportunities.repository import OpportunityRepository
from app.resumes.repository import LaneRepository, ResumeRepository
from app.state_machines.opportunity import (
    OPPORTUNITY_DECIDED,
    OpportunityCommand,
    opportunity_transition,
)


class DecisionService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.opportunities = OpportunityRepository(session)
        self.applications = ApplicationService(session)
        self.resumes = ResumeRepository(session)
        self.lanes = LaneRepository(session)
        self.events = DomainEventRepository(session)

    def decide(
        self,
        *,
        user_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        command: OpportunityCommand,
        expected_state_version: int,
        reason: str | None,
        actor: Actor = Actor.USER,
        source_ref_id: uuid.UUID | None = None,
        commit: bool = True,
    ) -> None:
        def work() -> None:
            row = self._lock(user_id, opportunity_id, expected_state_version)
            self._transition(
                row,
                command,
                occurred_at=database_now(self.session),
                reason=reason,
                actor=actor,
                source_ref_id=source_ref_id,
                correlation_id=None,
            )

        run_in_transaction(self.session, work, commit=commit)

    def apply(
        self,
        *,
        user_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        expected_state_version: int,
        resume_id: uuid.UUID | None,
        lane_id: uuid.UUID | None,
        channel: ApplicationChannel,
        applied_at: datetime | None,
        actor: Actor = Actor.USER,
        source_ref_id: uuid.UUID | None = None,
        commit: bool = True,
    ) -> Application:
        def work() -> Application:
            row = self._lock(user_id, opportunity_id, expected_state_version)
            opportunity_transition(row.status, OpportunityCommand.APPLY)
            self._require_active(user_id, resume_id, lane_id)
            moment = database_now(self.session) if applied_at is None else applied_at
            refuse_future(self.session, moment)
            correlation_id = new_id()
            self._transition(
                row,
                OpportunityCommand.APPLY,
                occurred_at=moment,
                reason=None,
                actor=actor,
                source_ref_id=source_ref_id,
                correlation_id=correlation_id,
            )
            return self.applications.create(
                user_id=user_id,
                opportunity_id=row.id,
                resume_id=resume_id,
                lane_id=lane_id,
                channel=channel,
                applied_at=moment,
                correlation_id=correlation_id,
                actor=actor,
                source_ref_id=source_ref_id,
            )

        return run_in_transaction(self.session, work, commit=commit)

    def _lock(self, user_id: uuid.UUID, opportunity_id: uuid.UUID, expected: int) -> Opportunity:
        row = self.opportunities.lock(user_id=user_id, id=opportunity_id)
        if row.state_version != expected:
            raise ConcurrencyConflict("opportunities")
        return row

    def _require_active(
        self, user_id: uuid.UUID, resume_id: uuid.UUID | None, lane_id: uuid.UUID | None
    ) -> None:
        if resume_id is not None:
            resume = self.resumes.get(user_id=user_id, id=resume_id)
            if resume.status is not ResumeStatus.ACTIVE:
                raise ApiError(422, "resume_archived")
        if lane_id is not None:
            lane = self.lanes.get(user_id=user_id, id=lane_id)
            if lane.status is not LaneStatus.ACTIVE:
                raise ApiError(422, "lane_archived")

    def _transition(
        self,
        row: Opportunity,
        command: OpportunityCommand,
        *,
        occurred_at: datetime,
        reason: str | None,
        actor: Actor,
        source_ref_id: uuid.UUID | None,
        correlation_id: uuid.UUID | None,
    ) -> None:
        previous: OpportunityStatus = row.status
        result = opportunity_transition(previous, command)
        user_id, opportunity_id = row.user_id, row.id
        self.opportunities.update_fields(
            user_id=user_id,
            id=opportunity_id,
            values={"status": result.new_status},
            expected_version=row.state_version,
        )
        self.events.append(
            user_id=user_id,
            aggregate_type=AggregateType.OPPORTUNITY,
            aggregate_id=opportunity_id,
            event_type=OPPORTUNITY_DECIDED,
            occurred_at=occurred_at,
            actor=actor,
            payload=OpportunityDecided(
                opportunity_id=opportunity_id,
                decision=command.value,
                from_status=previous.value,
                to_status=result.new_status.value,
                reason=reason,
            ),
            source_ref_id=source_ref_id,
            correlation_id=correlation_id,
        )
