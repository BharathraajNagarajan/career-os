import uuid
from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.auth.deps import current_auth, get_db_session, verify_csrf
from app.auth.service import AuthContext
from app.core.errors import ApiError, ErrorResponse
from app.core.logging import get_logger
from app.db.models import ReviewItem, ReviewStatus
from app.db.tenancy import NotFound
from app.db.versioning import ConcurrencyConflict
from app.review.errors import InvalidPayload, InvalidTransition, NoHandler, ReviewError
from app.review.handlers import ReviewHandlerRegistry
from app.review.schemas import (
    BatchConfirmRequest,
    BatchConfirmResponse,
    BatchConfirmResult,
    ConfirmRequest,
    EditConfirmRequest,
    RejectRequest,
    ReviewItemResponse,
)
from app.review.service import ReviewService

log = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/review-items",
    tags=["review"],
    dependencies=[Depends(verify_csrf)],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)

NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"model": ErrorResponse}}
DECISION_ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}

T = TypeVar("T")

Auth = Annotated[AuthContext, Depends(current_auth)]
DbSession = Annotated[Session, Depends(get_db_session)]


def get_registry(request: Request) -> ReviewHandlerRegistry:
    registry: ReviewHandlerRegistry = request.app.state.review_registry
    return registry


def review_service(
    session: DbSession, registry: Annotated[ReviewHandlerRegistry, Depends(get_registry)]
) -> ReviewService:
    return ReviewService(session, registry)


Service = Annotated[ReviewService, Depends(review_service)]


def respond(service: ReviewService, item: ReviewItem) -> ReviewItemResponse:
    return ReviewItemResponse.build(
        item, confirmable=service.registry.get(item.proposal_type) is not None
    )


def guarded(action: Callable[[], ReviewItem], service: ReviewService) -> ReviewItemResponse:
    try:
        return respond(service, action())
    except ConcurrencyConflict as exc:
        raise ApiError(409, "conflict") from exc
    except InvalidTransition as exc:
        raise ApiError(409, exc.code) from exc
    except NoHandler as exc:
        raise ApiError(422, exc.code) from exc
    except InvalidPayload as exc:
        raise ApiError(422, exc.code) from exc


@router.get("", response_model=list[ReviewItemResponse])
def list_review_items(
    auth: Auth,
    service: Service,
    status: ReviewStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[ReviewItemResponse]:
    return [
        respond(service, item)
        for item in service.list(user_id=auth.user_id, status=status, limit=limit)
    ]


def failure_code(exc: Exception) -> str:
    if isinstance(exc, NotFound):
        return "not_found"
    if isinstance(exc, ConcurrencyConflict):
        return "conflict"
    if isinstance(exc, ReviewError):
        return exc.code
    if isinstance(exc, ApiError):
        return exc.code
    return "error"


@router.post("/batch-confirm", response_model=BatchConfirmResponse)
def batch_confirm(body: BatchConfirmRequest, auth: Auth, service: Service) -> BatchConfirmResponse:
    results: list[BatchConfirmResult] = []
    for entry in body.items:
        try:
            item = service.confirm(
                user_id=auth.user_id,
                item_id=entry.id,
                expected_state_version=entry.expected_state_version,
            )
        except Exception as exc:
            service.session.rollback()
            code = failure_code(exc)
            if code == "error":
                log.error("batch_confirm_item_failed", error_type=type(exc).__name__)
            results.append(BatchConfirmResult(id=entry.id, ok=False, error_code=code, item=None))
        else:
            results.append(
                BatchConfirmResult(
                    id=entry.id, ok=True, error_code=None, item=respond(service, item)
                )
            )
    return BatchConfirmResponse(results=results)


@router.get("/{item_id}", response_model=ReviewItemResponse, responses=NOT_FOUND)
def get_review_item(item_id: uuid.UUID, auth: Auth, service: Service) -> ReviewItemResponse:
    return respond(service, service.get(user_id=auth.user_id, item_id=item_id))


@router.post("/{item_id}/confirm", response_model=ReviewItemResponse, responses=DECISION_ERRORS)
def confirm_review_item(
    item_id: uuid.UUID, body: ConfirmRequest, auth: Auth, service: Service
) -> ReviewItemResponse:
    return guarded(
        lambda: service.confirm(
            user_id=auth.user_id,
            item_id=item_id,
            expected_state_version=body.expected_state_version,
        ),
        service,
    )


@router.post(
    "/{item_id}/edit-confirm", response_model=ReviewItemResponse, responses=DECISION_ERRORS
)
def edit_confirm_review_item(
    item_id: uuid.UUID, body: EditConfirmRequest, auth: Auth, service: Service
) -> ReviewItemResponse:
    return guarded(
        lambda: service.edit_confirm(
            user_id=auth.user_id,
            item_id=item_id,
            expected_state_version=body.expected_state_version,
            payload=body.payload,
        ),
        service,
    )


@router.post("/{item_id}/reject", response_model=ReviewItemResponse, responses=DECISION_ERRORS)
def reject_review_item(
    item_id: uuid.UUID, body: RejectRequest, auth: Auth, service: Service
) -> ReviewItemResponse:
    return guarded(
        lambda: service.reject(
            user_id=auth.user_id,
            item_id=item_id,
            expected_state_version=body.expected_state_version,
            note=body.note,
        ),
        service,
    )
