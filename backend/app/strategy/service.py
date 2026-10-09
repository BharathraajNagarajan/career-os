import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.applications.service import run_in_transaction
from app.db.models import Company, ResumeLane, RuleScope, RuleType, StrategyRule
from app.db.tenancy import require_user_id, resolve_owned
from app.strategy.schemas import RuleCondition

LIST_LIMIT = 200


class RuleService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_for_user(
        self, *, user_id: uuid.UUID, scope: RuleScope | None, active: bool | None
    ) -> Sequence[StrategyRule]:
        statement = select(StrategyRule).where(StrategyRule.user_id == require_user_id(user_id))
        if scope is not None:
            statement = statement.where(StrategyRule.scope == scope)
        if active is not None:
            statement = statement.where(StrategyRule.active == active)
        return self.session.scalars(
            statement.order_by(StrategyRule.created_at.desc(), StrategyRule.id.desc()).limit(
                LIST_LIMIT
            )
        ).all()

    def create(
        self,
        *,
        user_id: uuid.UUID,
        scope: RuleScope,
        company_id: uuid.UUID | None,
        lane_id: uuid.UUID | None,
        statement: str,
        rule_type: RuleType,
        condition: RuleCondition | None,
        active: bool,
    ) -> StrategyRule:
        def work() -> StrategyRule:
            if company_id is not None:
                resolve_owned(self.session, Company, user_id=user_id, id=company_id)
            if lane_id is not None:
                resolve_owned(self.session, ResumeLane, user_id=user_id, id=lane_id)
            row = StrategyRule(
                user_id=user_id,
                scope=scope,
                company_id=company_id,
                lane_id=lane_id,
                statement=statement,
                rule_type=rule_type,
                condition=None if condition is None else condition.model_dump(mode="json"),
                active=active,
            )
            self.session.add(row)
            self.session.flush()
            return row

        return run_in_transaction(self.session, work, commit=True)

    def get(self, *, user_id: uuid.UUID, rule_id: uuid.UUID) -> StrategyRule:
        return resolve_owned(self.session, StrategyRule, user_id=user_id, id=rule_id)

    def edit(
        self, *, user_id: uuid.UUID, rule_id: uuid.UUID, changes: dict[str, Any]
    ) -> StrategyRule:
        def work() -> StrategyRule:
            row = self.get(user_id=user_id, rule_id=rule_id)
            for name in ("statement", "rule_type", "active"):
                if changes.get(name) is not None:
                    setattr(row, name, changes[name])
            if "condition" in changes:
                condition = changes["condition"]
                row.condition = (
                    None
                    if condition is None
                    else RuleCondition.model_validate(condition).model_dump(mode="json")
                )
            self.session.flush()
            return row

        return run_in_transaction(self.session, work, commit=True)

    def delete(self, *, user_id: uuid.UUID, rule_id: uuid.UUID) -> None:
        def work() -> None:
            self.session.delete(self.get(user_id=user_id, rule_id=rule_id))
            self.session.flush()

        run_in_transaction(self.session, work, commit=True)
