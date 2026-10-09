import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.deps import current_auth, get_db_session, verify_csrf
from app.auth.service import AuthContext
from app.core.errors import ErrorResponse
from app.interactions.schemas import InteractionCreate, InteractionResponse
from app.interactions.service import InteractionService

router = APIRouter(
    prefix="/api/v1",
    tags=["interactions"],
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


def interaction_service(session: DbSession) -> InteractionService:
    return InteractionService(session)


Interactions = Annotated[InteractionService, Depends(interaction_service)]


@router.get("/interactions", response_model=list[InteractionResponse])
def list_interactions(
    auth: Auth,
    service: Interactions,
    contact_id: Annotated[uuid.UUID | None, Query()] = None,
    opportunity_id: Annotated[uuid.UUID | None, Query()] = None,
    application_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[InteractionResponse]:
    rows = service.list_for_user(
        user_id=auth.user_id,
        contact_id=contact_id,
        opportunity_id=opportunity_id,
        application_id=application_id,
    )
    return [InteractionResponse.build(row) for row in rows]


@router.get(
    "/interactions/{interaction_id}", response_model=InteractionResponse, responses=NOT_FOUND
)
def get_interaction(
    interaction_id: uuid.UUID, auth: Auth, service: Interactions
) -> InteractionResponse:
    return InteractionResponse.build(
        service.get(user_id=auth.user_id, interaction_id=interaction_id)
    )


@router.post(
    "/interactions", response_model=InteractionResponse, status_code=201, responses=COMMAND_ERRORS
)
def create_interaction(
    body: InteractionCreate, auth: Auth, service: Interactions
) -> InteractionResponse:
    row, application_state_version = service.create(
        user_id=auth.user_id,
        contact_id=body.contact_id,
        channel=body.channel,
        direction=body.direction,
        occurred_at=body.occurred_at,
        summary=body.summary,
        opportunity_id=body.opportunity_id,
        application_id=body.application_id,
        application_event_type=body.application_event_type,
        expected_application_state_version=body.expected_application_state_version,
    )
    return InteractionResponse.build(row, application_state_version=application_state_version)
