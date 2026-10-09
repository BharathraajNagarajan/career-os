import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.applications.service import ApplicationService, refuse_future, run_in_transaction
from app.core.errors import ApiError
from app.db.models import (
    Application,
    Contact,
    Interaction,
    InteractionChannel,
    InteractionDirection,
    Opportunity,
)
from app.db.tenancy import require_user_id, resolve_owned
from app.state_machines.application import ApplicationEventType
from app.state_machines.errors import EventTypeNotAllowed

E = ApplicationEventType
INTERACTION_EVENT_TYPES = frozenset(
    {
        E.OUTREACH_SENT,
        E.FOLLOWUP_SENT,
        E.RECRUITER_CONTACTED,
        E.CONTACT_REPLIED,
        E.CONNECTION_REQUEST_SENT,
        E.CONNECTION_ACCEPTED,
    }
)
LIST_LIMIT = 200


class InteractionService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, *, user_id: uuid.UUID, interaction_id: uuid.UUID) -> Interaction:
        return resolve_owned(self.session, Interaction, user_id=user_id, id=interaction_id)

    def list_for_user(
        self,
        *,
        user_id: uuid.UUID,
        contact_id: uuid.UUID | None,
        opportunity_id: uuid.UUID | None,
        application_id: uuid.UUID | None,
    ) -> Sequence[Interaction]:
        statement = select(Interaction).where(Interaction.user_id == require_user_id(user_id))
        if contact_id is not None:
            statement = statement.where(Interaction.contact_id == contact_id)
        if opportunity_id is not None:
            statement = statement.where(Interaction.opportunity_id == opportunity_id)
        if application_id is not None:
            statement = statement.where(Interaction.application_id == application_id)
        return self.session.scalars(
            statement.order_by(Interaction.occurred_at.desc(), Interaction.id.desc()).limit(
                LIST_LIMIT
            )
        ).all()

    def create(
        self,
        *,
        user_id: uuid.UUID,
        contact_id: uuid.UUID,
        channel: InteractionChannel,
        direction: InteractionDirection,
        occurred_at: datetime,
        summary: str | None,
        opportunity_id: uuid.UUID | None,
        application_id: uuid.UUID | None,
        application_event_type: ApplicationEventType | None,
        expected_application_state_version: int | None,
    ) -> tuple[Interaction, int | None]:
        if application_event_type is not None:
            if application_id is None:
                raise ApiError(422, "application_required")
            if application_event_type not in INTERACTION_EVENT_TYPES:
                raise EventTypeNotAllowed(application_event_type.value)
            if expected_application_state_version is None:
                raise ApiError(422, "expected_application_state_version_required")

        def work() -> tuple[Interaction, int | None]:
            resolve_owned(self.session, Contact, user_id=user_id, id=contact_id)
            linked_opportunity = opportunity_id
            if application_id is not None:
                application = resolve_owned(
                    self.session, Application, user_id=user_id, id=application_id
                )
                if opportunity_id is not None and application.opportunity_id != opportunity_id:
                    raise ApiError(422, "application_opportunity_mismatch")
                linked_opportunity = application.opportunity_id
            company_id = None
            if linked_opportunity is not None:
                opportunity = resolve_owned(
                    self.session, Opportunity, user_id=user_id, id=linked_opportunity
                )
                company_id = opportunity.company_id
            refuse_future(self.session, occurred_at)
            row = Interaction(
                user_id=user_id,
                contact_id=contact_id,
                company_id=company_id,
                opportunity_id=linked_opportunity,
                application_id=application_id,
                channel=channel,
                direction=direction,
                occurred_at=occurred_at,
                summary=summary,
            )
            self.session.add(row)
            self.session.flush()
            new_version: int | None = None
            if (
                application_event_type is not None
                and application_id is not None
                and expected_application_state_version is not None
            ):
                new_version = ApplicationService(self.session).record_event(
                    user_id=user_id,
                    application_id=application_id,
                    expected_state_version=expected_application_state_version,
                    event_type=application_event_type,
                    occurred_at=occurred_at,
                    note=None,
                    interaction_id=row.id,
                    commit=False,
                )
            return row, new_version

        row, version = run_in_transaction(self.session, work, commit=True)
        return self.get(user_id=user_id, interaction_id=row.id), version
