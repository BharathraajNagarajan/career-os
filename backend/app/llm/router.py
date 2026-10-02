from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.auth.deps import current_auth, get_db_session, verify_csrf
from app.auth.service import AuthContext
from app.config import Settings
from app.core.errors import ErrorResponse
from app.llm.gateway import utc_now
from app.llm.repository import LlmRunRepository, next_budget_reset
from app.llm.schemas import BudgetResponse

router = APIRouter(
    prefix="/api/v1/llm",
    tags=["llm"],
    dependencies=[Depends(verify_csrf)],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)

Auth = Annotated[AuthContext, Depends(current_auth)]
DbSession = Annotated[Session, Depends(get_db_session)]


def get_settings_from_app(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


@router.get("/budget", response_model=BudgetResponse)
def get_budget(
    auth: Auth, session: DbSession, settings: Annotated[Settings, Depends(get_settings_from_app)]
) -> BudgetResponse:
    now = utc_now()
    spent = LlmRunRepository(session).spent_in_day(user_id=auth.user_id, now=now)
    cap = settings.llm_daily_cost_cap_usd
    return BudgetResponse(
        spent_usd=spent,
        cap_usd=cap,
        remaining_usd=max(cap - spent, Decimal(0)),
        resets_at=next_budget_reset(now),
    )
