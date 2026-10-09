import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.auth.deps import current_auth, get_db_session, verify_csrf
from app.auth.service import AuthContext
from app.core.errors import ErrorResponse
from app.db.models import RuleScope
from app.strategy.schemas import RuleCreate, RulePatch, RuleResponse
from app.strategy.service import RuleService

router = APIRouter(
    prefix="/api/v1",
    tags=["strategy-rules"],
    dependencies=[Depends(verify_csrf)],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)

NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"model": ErrorResponse}}
COMMAND_ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}

Auth = Annotated[AuthContext, Depends(current_auth)]
DbSession = Annotated[Session, Depends(get_db_session)]


def rule_service(session: DbSession) -> RuleService:
    return RuleService(session)


Rules = Annotated[RuleService, Depends(rule_service)]


@router.get("/strategy-rules", response_model=list[RuleResponse])
def list_rules(
    auth: Auth,
    service: Rules,
    scope: Annotated[RuleScope | None, Query()] = None,
    active: Annotated[bool | None, Query()] = None,
) -> list[RuleResponse]:
    rows = service.list_for_user(user_id=auth.user_id, scope=scope, active=active)
    return [RuleResponse.build(row) for row in rows]


@router.post(
    "/strategy-rules", response_model=RuleResponse, status_code=201, responses=COMMAND_ERRORS
)
def create_rule(body: RuleCreate, auth: Auth, service: Rules) -> RuleResponse:
    row = service.create(
        user_id=auth.user_id,
        scope=body.scope,
        company_id=body.company_id,
        lane_id=body.lane_id,
        statement=body.statement,
        rule_type=body.rule_type,
        condition=body.condition,
        active=body.active,
    )
    return RuleResponse.build(row)


@router.patch("/strategy-rules/{rule_id}", response_model=RuleResponse, responses=COMMAND_ERRORS)
def edit_rule(rule_id: uuid.UUID, body: RulePatch, auth: Auth, service: Rules) -> RuleResponse:
    row = service.edit(
        user_id=auth.user_id, rule_id=rule_id, changes=body.model_dump(exclude_unset=True)
    )
    return RuleResponse.build(row)


@router.delete("/strategy-rules/{rule_id}", status_code=204, responses=NOT_FOUND)
def delete_rule(rule_id: uuid.UUID, auth: Auth, service: Rules) -> Response:
    service.delete(user_id=auth.user_id, rule_id=rule_id)
    return Response(status_code=204)
