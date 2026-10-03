import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.applications.schemas import (
    ApplicationResponse,
    RecordEventRequest,
    ReopenRequest,
    VoidEventRequest,
)
from app.applications.service import ApplicationService
from app.auth.deps import current_auth, get_db_session, verify_csrf
from app.auth.service import AuthContext
from app.core.errors import ErrorResponse
from app.db.models import ApplicationStage

router = APIRouter(
    prefix="/api/v1",
    tags=["applications"],
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


def application_service(session: DbSession) -> ApplicationService:
    return ApplicationService(session)


Applications = Annotated[ApplicationService, Depends(application_service)]


def respond(
    service: ApplicationService, user_id: uuid.UUID, application_id: uuid.UUID
) -> ApplicationResponse:
    row, opportunity, company = service.get(user_id=user_id, application_id=application_id)
    return ApplicationResponse.build(row, opportunity, company)


@router.get("/applications", response_model=list[ApplicationResponse])
def list_applications(
    auth: Auth,
    service: Applications,
    stage: Annotated[ApplicationStage | None, Query()] = None,
    is_terminal: Annotated[bool | None, Query()] = None,
    opportunity_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[ApplicationResponse]:
    rows = service.list_for_user(
        user_id=auth.user_id, stage=stage, is_terminal=is_terminal, opportunity_id=opportunity_id
    )
    return [ApplicationResponse.build(*row) for row in rows]


@router.get(
    "/applications/{application_id}", response_model=ApplicationResponse, responses=NOT_FOUND
)
def get_application(
    application_id: uuid.UUID, auth: Auth, service: Applications
) -> ApplicationResponse:
    return respond(service, auth.user_id, application_id)


@router.post(
    "/applications/{application_id}/events",
    response_model=ApplicationResponse,
    responses=COMMAND_ERRORS,
)
def record_application_event(
    application_id: uuid.UUID, body: RecordEventRequest, auth: Auth, service: Applications
) -> ApplicationResponse:
    service.record_event(
        user_id=auth.user_id,
        application_id=application_id,
        expected_state_version=body.expected_state_version,
        event_type=body.event_type,
        occurred_at=body.occurred_at,
        note=body.note,
    )
    return respond(service, auth.user_id, application_id)


@router.post(
    "/applications/{application_id}/events/{event_id}/void",
    response_model=ApplicationResponse,
    responses=COMMAND_ERRORS,
)
def void_application_event(
    application_id: uuid.UUID,
    event_id: uuid.UUID,
    body: VoidEventRequest,
    auth: Auth,
    service: Applications,
) -> ApplicationResponse:
    service.void_event(
        user_id=auth.user_id,
        application_id=application_id,
        expected_state_version=body.expected_state_version,
        event_id=event_id,
        reason=body.reason,
    )
    return respond(service, auth.user_id, application_id)


@router.post(
    "/applications/{application_id}/reopen",
    response_model=ApplicationResponse,
    responses=COMMAND_ERRORS,
)
def reopen_application(
    application_id: uuid.UUID, body: ReopenRequest, auth: Auth, service: Applications
) -> ApplicationResponse:
    service.reopen(
        user_id=auth.user_id,
        application_id=application_id,
        expected_state_version=body.expected_state_version,
        note=body.note,
    )
    return respond(service, auth.user_id, application_id)
