import uuid
from collections.abc import Sequence
from typing import cast

from sqlalchemy import Select, Table, and_, func, select

from app.db.models import (
    Application,
    ApplicationStage,
    Company,
    DomainEvent,
    Opportunity,
)
from app.db.tenancy import NotFound, UserScopedRepository, require_user_id
from app.db.versioning import update_versioned
from app.state_machines.application import ApplicationEventType, EventRecord

LIST_LIMIT = 200

ApplicationRow = tuple[Application, Opportunity, Company | None]


def event_record(event: DomainEvent) -> EventRecord:
    return EventRecord(
        id=event.id,
        event_type=ApplicationEventType(event.event_type),
        occurred_at=event.occurred_at,
        recorded_at=event.recorded_at,
        voids_event_id=event.voids_event_id,
    )


class ApplicationRepository(UserScopedRepository[Application]):
    model = Application

    def _with_context(self, user_id: uuid.UUID) -> Select[Application, Opportunity, Company]:
        return (
            select(Application, Opportunity, Company)
            .join(
                Opportunity,
                and_(
                    Opportunity.user_id == Application.user_id,
                    Opportunity.id == Application.opportunity_id,
                ),
            )
            .outerjoin(
                Company,
                and_(Company.user_id == Opportunity.user_id, Company.id == Opportunity.company_id),
            )
            .where(Application.user_id == require_user_id(user_id))
        )

    def list_with_context(
        self,
        *,
        user_id: uuid.UUID,
        stage: ApplicationStage | None = None,
        is_terminal: bool | None = None,
        opportunity_id: uuid.UUID | None = None,
    ) -> Sequence[ApplicationRow]:
        statement = self._with_context(user_id)
        if stage is not None:
            statement = statement.where(Application.stage == stage)
        if is_terminal is not None:
            statement = statement.where(Application.is_terminal == is_terminal)
        if opportunity_id is not None:
            statement = statement.where(Application.opportunity_id == opportunity_id)
        statement = statement.order_by(Application.applied_at.desc(), Application.id.desc()).limit(
            LIST_LIMIT
        )
        return list(self.session.execute(statement))

    def get_with_context(self, *, user_id: uuid.UUID, id: uuid.UUID) -> ApplicationRow:
        row = self.session.execute(
            self._with_context(user_id).where(Application.id == id)
        ).one_or_none()
        if row is None:
            raise NotFound("Application")
        return row

    def lock(self, *, user_id: uuid.UUID, id: uuid.UUID) -> Application:
        row = self.session.scalars(
            select(Application)
            .where(Application.user_id == require_user_id(user_id), Application.id == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one_or_none()
        if row is None:
            raise NotFound("Application")
        return row

    def ids_for_opportunity(
        self, *, user_id: uuid.UUID, opportunity_id: uuid.UUID
    ) -> Sequence[uuid.UUID]:
        return self.session.scalars(
            select(Application.id).where(
                Application.user_id == require_user_id(user_id),
                Application.opportunity_id == opportunity_id,
            )
        ).all()

    def write_projection(
        self,
        *,
        user_id: uuid.UUID,
        id: uuid.UUID,
        expected_version: int,
        stage: ApplicationStage,
        is_terminal: bool,
    ) -> int:
        self.session.flush()
        version = update_versioned(
            self.session,
            cast(Table, Application.__table__),
            user_id=user_id,
            id=id,
            expected_version=expected_version,
            values={"stage": stage, "is_terminal": is_terminal, "updated_at": func.now()},
        )
        self.session.expire_all()
        return version
