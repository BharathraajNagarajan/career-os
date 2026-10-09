import uuid
from collections.abc import Sequence

from sqlalchemy import select

from app.db.models import RecruitingAction, RecruitingActionKind, RecruitingActionStatus
from app.db.tenancy import NotFound, UserScopedRepository, require_user_id

LIST_LIMIT = 200


class RecruitingActionRepository(UserScopedRepository[RecruitingAction]):
    model = RecruitingAction

    def lock(self, *, user_id: uuid.UUID, id: uuid.UUID) -> RecruitingAction:
        row = self.session.scalars(
            select(RecruitingAction)
            .where(RecruitingAction.user_id == require_user_id(user_id), RecruitingAction.id == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one_or_none()
        if row is None:
            raise NotFound("RecruitingAction")
        return row

    def list_filtered(
        self,
        *,
        user_id: uuid.UUID,
        statuses: Sequence[RecruitingActionStatus] | None = None,
        kind: RecruitingActionKind | None = None,
        opportunity_id: uuid.UUID | None = None,
        application_id: uuid.UUID | None = None,
        contact_id: uuid.UUID | None = None,
    ) -> Sequence[RecruitingAction]:
        statement = select(RecruitingAction).where(
            RecruitingAction.user_id == require_user_id(user_id)
        )
        if statuses:
            statement = statement.where(RecruitingAction.status.in_(statuses))
        if kind is not None:
            statement = statement.where(RecruitingAction.kind == kind)
        if opportunity_id is not None:
            statement = statement.where(RecruitingAction.opportunity_id == opportunity_id)
        if application_id is not None:
            statement = statement.where(RecruitingAction.application_id == application_id)
        if contact_id is not None:
            statement = statement.where(RecruitingAction.contact_id == contact_id)
        return self.session.scalars(
            statement.order_by(
                RecruitingAction.due_at.asc().nulls_last(),
                RecruitingAction.created_at.desc(),
                RecruitingAction.id,
            ).limit(LIST_LIMIT)
        ).all()

    def count_follow_ups(
        self,
        *,
        user_id: uuid.UUID,
        application_id: uuid.UUID | None,
        opportunity_id: uuid.UUID | None,
        contact_id: uuid.UUID | None,
    ) -> int:
        scope = (
            RecruitingAction.application_id == application_id
            if application_id is not None
            else RecruitingAction.opportunity_id == opportunity_id
            if opportunity_id is not None
            else RecruitingAction.contact_id == contact_id
        )
        return len(
            self.session.scalars(
                select(RecruitingAction.id).where(
                    RecruitingAction.user_id == require_user_id(user_id),
                    RecruitingAction.kind == RecruitingActionKind.FOLLOW_UP,
                    scope,
                )
            ).all()
        )
