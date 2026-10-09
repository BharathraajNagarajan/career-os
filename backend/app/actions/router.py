import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.actions.schemas import (
    ActionCreate,
    ActionPatch,
    ActionResponse,
    ActionSnooze,
    ActionVersion,
)
from app.actions.service import ActionService
from app.auth.deps import current_auth, get_db_session, verify_csrf
from app.auth.service import AuthContext
from app.core.errors import ErrorResponse
from app.db.models import RecruitingActionKind, RecruitingActionStatus
from app.state_machines.recruiting_action import RecruitingActionCommand

router = APIRouter(
    prefix="/api/v1",
    tags=["actions"],
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


def action_service(session: DbSession) -> ActionService:
    return ActionService(session)


Actions = Annotated[ActionService, Depends(action_service)]


@router.get("/actions", response_model=list[ActionResponse])
def list_actions(
    auth: Auth,
    service: Actions,
    status: Annotated[list[RecruitingActionStatus] | None, Query()] = None,
    kind: Annotated[RecruitingActionKind | None, Query()] = None,
    opportunity_id: Annotated[uuid.UUID | None, Query()] = None,
    application_id: Annotated[uuid.UUID | None, Query()] = None,
    contact_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[ActionResponse]:
    rows = service.list_for_user(
        user_id=auth.user_id,
        statuses=status,
        kind=kind,
        opportunity_id=opportunity_id,
        application_id=application_id,
        contact_id=contact_id,
    )
    return [ActionResponse.build(row) for row in rows]


@router.get("/actions/{action_id}", response_model=ActionResponse, responses=NOT_FOUND)
def get_action(action_id: uuid.UUID, auth: Auth, service: Actions) -> ActionResponse:
    return ActionResponse.build(service.get(user_id=auth.user_id, action_id=action_id))


@router.post("/actions", response_model=ActionResponse, status_code=201, responses=COMMAND_ERRORS)
def create_action(body: ActionCreate, auth: Auth, service: Actions) -> ActionResponse:
    row = service.create(
        user_id=auth.user_id,
        kind=body.kind,
        title=body.title,
        due_at=body.due_at,
        opportunity_id=body.opportunity_id,
        application_id=body.application_id,
        contact_id=body.contact_id,
        interaction_id=body.interaction_id,
    )
    return ActionResponse.build(row)


@router.patch("/actions/{action_id}", response_model=ActionResponse, responses=COMMAND_ERRORS)
def edit_action(
    action_id: uuid.UUID, body: ActionPatch, auth: Auth, service: Actions
) -> ActionResponse:
    row = service.edit(
        user_id=auth.user_id,
        action_id=action_id,
        expected_state_version=body.expected_state_version,
        title=body.title,
        due_at=body.due_at,
        set_due_at="due_at" in body.model_fields_set,
    )
    return ActionResponse.build(row)


@router.post("/actions/{action_id}/snooze", response_model=ActionResponse, responses=COMMAND_ERRORS)
def snooze_action(
    action_id: uuid.UUID, body: ActionSnooze, auth: Auth, service: Actions
) -> ActionResponse:
    row = service.transition(
        user_id=auth.user_id,
        action_id=action_id,
        command=RecruitingActionCommand.SNOOZE,
        expected_state_version=body.expected_state_version,
        until=body.until,
    )
    return ActionResponse.build(row)


@router.post(
    "/actions/{action_id}/complete", response_model=ActionResponse, responses=COMMAND_ERRORS
)
def complete_action(
    action_id: uuid.UUID, body: ActionVersion, auth: Auth, service: Actions
) -> ActionResponse:
    row = service.transition(
        user_id=auth.user_id,
        action_id=action_id,
        command=RecruitingActionCommand.COMPLETE,
        expected_state_version=body.expected_state_version,
    )
    return ActionResponse.build(row)


@router.post(
    "/actions/{action_id}/dismiss", response_model=ActionResponse, responses=COMMAND_ERRORS
)
def dismiss_action(
    action_id: uuid.UUID, body: ActionVersion, auth: Auth, service: Actions
) -> ActionResponse:
    row = service.transition(
        user_id=auth.user_id,
        action_id=action_id,
        command=RecruitingActionCommand.DISMISS,
        expected_state_version=body.expected_state_version,
    )
    return ActionResponse.build(row)
