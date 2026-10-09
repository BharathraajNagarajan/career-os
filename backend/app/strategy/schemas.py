import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.models import RuleScope, RuleType, StrategyRule
from app.opportunities.normalize import clean_note

CONDITION_SCHEMA_VERSION = 1
STATEMENT_MAX_CHARS = 1000


class ConditionKind(StrEnum):
    APPLICATION_COOLDOWN = "application_cooldown"
    OUTREACH_COOLDOWN = "outreach_cooldown"


class RuleCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = CONDITION_SCHEMA_VERSION
    kind: ConditionKind
    days: int = Field(ge=1, le=365)

    @field_validator("schema_version")
    @classmethod
    def _known_version(cls, value: int) -> int:
        if value != CONDITION_SCHEMA_VERSION:
            raise ValueError("unsupported schema_version")
        return value


def clean_statement(value: str) -> str:
    cleaned = clean_note(value)
    if cleaned is None:
        raise ValueError("statement is required")
    return cleaned


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuleCreate(StrictModel):
    scope: RuleScope
    company_id: uuid.UUID | None = None
    lane_id: uuid.UUID | None = None
    statement: str = Field(max_length=STATEMENT_MAX_CHARS)
    rule_type: RuleType
    condition: RuleCondition | None = None
    active: bool = True

    @field_validator("statement")
    @classmethod
    def _clean_statement(cls, value: str) -> str:
        return clean_statement(value)

    @model_validator(mode="after")
    def _scope_matches_target(self) -> Self:
        company, lane = self.company_id, self.lane_id
        matches = (
            (self.scope is RuleScope.GLOBAL and company is None and lane is None)
            or (self.scope is RuleScope.COMPANY and company is not None and lane is None)
            or (self.scope is RuleScope.LANE and lane is not None and company is None)
        )
        if not matches:
            raise ValueError("scope does not match its target")
        return self


class RulePatch(StrictModel):
    statement: str | None = Field(default=None, max_length=STATEMENT_MAX_CHARS)
    rule_type: RuleType | None = None
    condition: RuleCondition | None = None
    active: bool | None = None

    @field_validator("statement")
    @classmethod
    def _clean_statement(cls, value: str | None) -> str | None:
        return None if value is None else clean_statement(value)


class RuleResponse(BaseModel):
    id: uuid.UUID
    scope: RuleScope
    company_id: uuid.UUID | None
    lane_id: uuid.UUID | None
    statement: str
    rule_type: RuleType
    condition: RuleCondition | None
    active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(cls, row: StrategyRule) -> Self:
        condition: dict[str, Any] | None = row.condition
        return cls(
            id=row.id,
            scope=row.scope,
            company_id=row.company_id,
            lane_id=row.lane_id,
            statement=row.statement,
            rule_type=row.rule_type,
            condition=None if condition is None else RuleCondition.model_validate(condition),
            active=row.active,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
