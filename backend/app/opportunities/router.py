import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.applications.schemas import ApplicationResponse, ApplyResponse, TimelineEntryResponse
from app.applications.service import ApplicationService
from app.applications.timeline import build_timeline
from app.artifacts.storage import StorageAdapter
from app.auth.deps import current_auth, get_db_session, verify_csrf
from app.auth.service import AuthContext
from app.config import Settings
from app.core.errors import ErrorResponse
from app.db.models import OpportunityStatus, Priority
from app.opportunities.company_service import CompanyService
from app.opportunities.decisions import DecisionService
from app.opportunities.schemas import (
    ApplyRequest,
    CompanyCreate,
    CompanyDetail,
    CompanyPatch,
    CompanyResponse,
    DecisionRequest,
    DuplicateMatch,
    IngestRequest,
    OpportunityDetail,
    OpportunityPatch,
    OpportunitySummary,
    PriorityRequest,
    QualificationCreate,
    QualificationPatch,
    QualificationResponse,
)
from app.opportunities.service import OpportunityService
from app.state_machines.opportunity import OpportunityCommand

router = APIRouter(
    prefix="/api/v1",
    tags=["opportunities"],
    dependencies=[Depends(verify_csrf)],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)

NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"model": ErrorResponse}}
EDIT_ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
}

Auth = Annotated[AuthContext, Depends(current_auth)]
DbSession = Annotated[Session, Depends(get_db_session)]


def get_settings_from_app(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_storage(request: Request) -> StorageAdapter:
    storage: StorageAdapter = request.app.state.storage
    return storage


def opportunity_service(
    session: DbSession,
    storage: Annotated[StorageAdapter, Depends(get_storage)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
) -> OpportunityService:
    return OpportunityService(session, storage, settings)


def company_service(session: DbSession) -> CompanyService:
    return CompanyService(session)


def decision_service(session: DbSession) -> DecisionService:
    return DecisionService(session)


Opportunities = Annotated[OpportunityService, Depends(opportunity_service)]
Decisions = Annotated[DecisionService, Depends(decision_service)]
COMMAND_ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}
Companies = Annotated[CompanyService, Depends(company_service)]


def detail(
    service: OpportunityService, user_id: uuid.UUID, opportunity_id: uuid.UUID
) -> OpportunityDetail:
    row, company, jd_text, qualifications = service.get_detail(
        user_id=user_id, opportunity_id=opportunity_id
    )
    return OpportunityDetail.build_detail(row, company, jd_text, list(qualifications))


@router.post(
    "/opportunities/ingest",
    status_code=202,
    response_model=OpportunitySummary,
    responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def ingest_opportunity(
    body: IngestRequest, auth: Auth, service: Opportunities
) -> OpportunitySummary:
    return service.ingest(user_id=auth.user_id, jd_text=body.jd_text, source_url=body.source_url)


@router.get("/opportunities", response_model=list[OpportunitySummary])
def list_opportunities(
    auth: Auth,
    service: Opportunities,
    status: Annotated[OpportunityStatus | None, Query()] = None,
    priority: Annotated[Priority | None, Query()] = None,
    company_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[OpportunitySummary]:
    return service.list_summaries(
        user_id=auth.user_id, status=status, priority=priority, company_id=company_id
    )


@router.get(
    "/opportunities/{opportunity_id}", response_model=OpportunityDetail, responses=NOT_FOUND
)
def get_opportunity(
    opportunity_id: uuid.UUID, auth: Auth, service: Opportunities
) -> OpportunityDetail:
    return detail(service, auth.user_id, opportunity_id)


@router.patch(
    "/opportunities/{opportunity_id}", response_model=OpportunityDetail, responses=EDIT_ERRORS
)
def patch_opportunity(
    opportunity_id: uuid.UUID, body: OpportunityPatch, auth: Auth, service: Opportunities
) -> OpportunityDetail:
    service.patch(user_id=auth.user_id, opportunity_id=opportunity_id, data=body)
    return detail(service, auth.user_id, opportunity_id)


@router.patch(
    "/opportunities/{opportunity_id}/priority",
    response_model=OpportunityDetail,
    responses=NOT_FOUND,
)
def set_opportunity_priority(
    opportunity_id: uuid.UUID, body: PriorityRequest, auth: Auth, service: Opportunities
) -> OpportunityDetail:
    service.set_priority(
        user_id=auth.user_id, opportunity_id=opportunity_id, priority=body.priority
    )
    return detail(service, auth.user_id, opportunity_id)


@router.post(
    "/opportunities/{opportunity_id}/extract",
    status_code=202,
    response_model=OpportunityDetail,
    responses=EDIT_ERRORS,
)
def retry_extraction(
    opportunity_id: uuid.UUID, auth: Auth, service: Opportunities
) -> OpportunityDetail:
    service.request_extraction(user_id=auth.user_id, opportunity_id=opportunity_id)
    return detail(service, auth.user_id, opportunity_id)


@router.get(
    "/opportunities/{opportunity_id}/duplicates",
    response_model=list[DuplicateMatch],
    responses=NOT_FOUND,
)
def list_duplicates(
    opportunity_id: uuid.UUID, auth: Auth, service: Opportunities
) -> list[DuplicateMatch]:
    return service.duplicates(user_id=auth.user_id, opportunity_id=opportunity_id)


@router.post(
    "/opportunities/{opportunity_id}/qualifications",
    status_code=201,
    response_model=QualificationResponse,
    responses=NOT_FOUND,
)
def add_qualification(
    opportunity_id: uuid.UUID, body: QualificationCreate, auth: Auth, service: Opportunities
) -> QualificationResponse:
    row = service.add_qualification(user_id=auth.user_id, opportunity_id=opportunity_id, data=body)
    return QualificationResponse.build(row)


@router.patch(
    "/qualifications/{qualification_id}",
    response_model=QualificationResponse,
    responses=NOT_FOUND,
)
def patch_qualification(
    qualification_id: uuid.UUID, body: QualificationPatch, auth: Auth, service: Opportunities
) -> QualificationResponse:
    row = service.update_qualification(
        user_id=auth.user_id, qualification_id=qualification_id, data=body
    )
    return QualificationResponse.build(row)


@router.delete("/qualifications/{qualification_id}", status_code=204, responses=NOT_FOUND)
def delete_qualification(
    qualification_id: uuid.UUID, auth: Auth, service: Opportunities
) -> Response:
    service.delete_qualification(user_id=auth.user_id, qualification_id=qualification_id)
    return Response(status_code=204)


@router.get("/companies", response_model=list[CompanyResponse])
def list_companies(auth: Auth, service: Companies) -> list[CompanyResponse]:
    return [CompanyResponse.build(row) for row in service.list(user_id=auth.user_id)]


@router.get("/companies/{company_id}", response_model=CompanyDetail, responses=NOT_FOUND)
def get_company(company_id: uuid.UUID, auth: Auth, service: Companies) -> CompanyDetail:
    company, counts = service.get_detail(user_id=auth.user_id, company_id=company_id)
    return CompanyDetail.build_detail(company, counts)


@router.post(
    "/companies",
    status_code=201,
    response_model=CompanyResponse,
    responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def create_company(body: CompanyCreate, auth: Auth, service: Companies) -> CompanyResponse:
    return CompanyResponse.build(service.create(user_id=auth.user_id, data=body))


@router.patch(
    "/companies/{company_id}",
    response_model=CompanyResponse,
    responses={**EDIT_ERRORS, 422: {"model": ErrorResponse}},
)
def patch_company(
    company_id: uuid.UUID, body: CompanyPatch, auth: Auth, service: Companies
) -> CompanyResponse:
    row = service.patch(user_id=auth.user_id, company_id=company_id, data=body)
    return CompanyResponse.build(row)


def decision_route(command: OpportunityCommand) -> None:
    def endpoint(
        opportunity_id: uuid.UUID,
        body: DecisionRequest,
        auth: Auth,
        decisions: Decisions,
        service: Opportunities,
    ) -> OpportunityDetail:
        decisions.decide(
            user_id=auth.user_id,
            opportunity_id=opportunity_id,
            command=command,
            expected_state_version=body.expected_state_version,
            reason=body.reason,
        )
        return detail(service, auth.user_id, opportunity_id)

    endpoint.__name__ = f"{command.value}_opportunity"
    router.add_api_route(
        f"/opportunities/{{opportunity_id}}/{command.value}",
        endpoint,
        methods=["POST"],
        response_model=OpportunityDetail,
        responses=COMMAND_ERRORS,
    )


for decision_command in (
    OpportunityCommand.SAVE,
    OpportunityCommand.SKIP,
    OpportunityCommand.CLOSE,
):
    decision_route(decision_command)


@router.post(
    "/opportunities/{opportunity_id}/apply",
    response_model=ApplyResponse,
    responses=COMMAND_ERRORS,
)
def apply_to_opportunity(
    opportunity_id: uuid.UUID,
    body: ApplyRequest,
    auth: Auth,
    decisions: Decisions,
    service: Opportunities,
) -> ApplyResponse:
    application = decisions.apply(
        user_id=auth.user_id,
        opportunity_id=opportunity_id,
        expected_state_version=body.expected_state_version,
        resume_id=body.resume_id,
        lane_id=body.lane_id,
        channel=body.channel,
        applied_at=body.applied_at,
    )
    row, opportunity, company = ApplicationService(decisions.session).get(
        user_id=auth.user_id, application_id=application.id
    )
    return ApplyResponse(
        opportunity=detail(service, auth.user_id, opportunity_id),
        application=ApplicationResponse.build(row, opportunity, company),
    )


@router.get(
    "/opportunities/{opportunity_id}/timeline",
    response_model=list[TimelineEntryResponse],
    responses=NOT_FOUND,
)
def opportunity_timeline(
    opportunity_id: uuid.UUID, auth: Auth, session: DbSession
) -> list[TimelineEntryResponse]:
    return [
        TimelineEntryResponse.model_validate(entry, from_attributes=True)
        for entry in build_timeline(session, user_id=auth.user_id, opportunity_id=opportunity_id)
    ]
