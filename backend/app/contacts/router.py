import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.deps import current_auth, get_db_session, verify_csrf
from app.auth.service import AuthContext
from app.contacts.schemas import (
    CompanyLinkRequest,
    ContactCreate,
    ContactDetail,
    ContactPatch,
    ContactSummary,
    MergeRequest,
    OpportunityLinkRequest,
)
from app.contacts.service import ContactService
from app.core.errors import ErrorResponse
from app.db.models import ContactOpportunityRole

router = APIRouter(
    prefix="/api/v1",
    tags=["contacts"],
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


def contact_service(session: DbSession) -> ContactService:
    return ContactService(session)


Contacts = Annotated[ContactService, Depends(contact_service)]


@router.get("/contacts", response_model=list[ContactSummary])
def list_contacts(
    auth: Auth,
    service: Contacts,
    q: Annotated[str | None, Query(max_length=200)] = None,
    company_id: Annotated[uuid.UUID | None, Query()] = None,
    opportunity_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[ContactSummary]:
    rows = service.list_for_user(
        user_id=auth.user_id, query=q, company_id=company_id, opportunity_id=opportunity_id
    )
    return [ContactSummary.build(row) for row in rows]


@router.get("/contacts/{contact_id}", response_model=ContactDetail, responses=NOT_FOUND)
def get_contact(contact_id: uuid.UUID, auth: Auth, service: Contacts) -> ContactDetail:
    return service.detail(user_id=auth.user_id, contact_id=contact_id)


@router.post("/contacts", response_model=ContactDetail, status_code=201, responses=COMMAND_ERRORS)
def create_contact(body: ContactCreate, auth: Auth, service: Contacts) -> ContactDetail:
    row = service.create(
        user_id=auth.user_id,
        full_name=body.full_name,
        emails=body.emails,
        linkedin_url=body.linkedin_url,
        headline=body.headline,
        notes=body.notes,
    )
    return service.detail(user_id=auth.user_id, contact_id=row.id)


@router.patch("/contacts/{contact_id}", response_model=ContactDetail, responses=COMMAND_ERRORS)
def edit_contact(
    contact_id: uuid.UUID, body: ContactPatch, auth: Auth, service: Contacts
) -> ContactDetail:
    service.edit(
        user_id=auth.user_id,
        contact_id=contact_id,
        expected_updated_at=body.expected_updated_at,
        changes=body.model_dump(exclude_unset=True, exclude={"expected_updated_at"}),
    )
    return service.detail(user_id=auth.user_id, contact_id=contact_id)


@router.post(
    "/contacts/{contact_id}/companies/{company_id}",
    response_model=ContactDetail,
    responses=COMMAND_ERRORS,
)
def link_company(
    contact_id: uuid.UUID,
    company_id: uuid.UUID,
    body: CompanyLinkRequest,
    auth: Auth,
    service: Contacts,
) -> ContactDetail:
    service.link_company(
        user_id=auth.user_id,
        contact_id=contact_id,
        company_id=company_id,
        relation=body.relation,
        title=body.title,
        is_current=body.is_current,
    )
    return service.detail(user_id=auth.user_id, contact_id=contact_id)


@router.delete(
    "/contacts/{contact_id}/companies/{company_id}",
    response_model=ContactDetail,
    responses=COMMAND_ERRORS,
)
def unlink_company(
    contact_id: uuid.UUID, company_id: uuid.UUID, auth: Auth, service: Contacts
) -> ContactDetail:
    service.unlink_company(user_id=auth.user_id, contact_id=contact_id, company_id=company_id)
    return service.detail(user_id=auth.user_id, contact_id=contact_id)


@router.post(
    "/contacts/{contact_id}/opportunities/{opportunity_id}",
    response_model=ContactDetail,
    responses=COMMAND_ERRORS,
)
def link_opportunity(
    contact_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    body: OpportunityLinkRequest,
    auth: Auth,
    service: Contacts,
) -> ContactDetail:
    service.link_opportunity(
        user_id=auth.user_id, contact_id=contact_id, opportunity_id=opportunity_id, role=body.role
    )
    return service.detail(user_id=auth.user_id, contact_id=contact_id)


@router.delete(
    "/contacts/{contact_id}/opportunities/{opportunity_id}",
    response_model=ContactDetail,
    responses=COMMAND_ERRORS,
)
def unlink_opportunity(
    contact_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    role: Annotated[ContactOpportunityRole, Query()],
    auth: Auth,
    service: Contacts,
) -> ContactDetail:
    service.unlink_opportunity(
        user_id=auth.user_id, contact_id=contact_id, opportunity_id=opportunity_id, role=role
    )
    return service.detail(user_id=auth.user_id, contact_id=contact_id)


@router.post(
    "/contacts/{survivor_id}/merge", response_model=ContactDetail, responses=COMMAND_ERRORS
)
def merge_contacts(
    survivor_id: uuid.UUID, body: MergeRequest, auth: Auth, service: Contacts
) -> ContactDetail:
    service.merge(
        user_id=auth.user_id,
        survivor_id=survivor_id,
        merged_id=body.merged_id,
        expected_survivor_updated_at=body.expected_survivor_updated_at,
        expected_merged_updated_at=body.expected_merged_updated_at,
    )
    return service.detail(user_id=auth.user_id, contact_id=survivor_id)
