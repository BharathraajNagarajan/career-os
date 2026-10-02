from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.deps import current_auth, get_db_session, verify_csrf
from app.auth.service import AuthContext
from app.core.errors import ErrorResponse
from app.profile.schemas import ProfileResponse, ProfileUpdate
from app.profile.service import ProfileService, to_response

router = APIRouter(
    prefix="/api/v1",
    tags=["profile"],
    dependencies=[Depends(verify_csrf)],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)

Auth = Annotated[AuthContext, Depends(current_auth)]
DbSession = Annotated[Session, Depends(get_db_session)]


@router.get("/profile", response_model=ProfileResponse)
def get_profile(auth: Auth, session: DbSession) -> ProfileResponse:
    return to_response(ProfileService(session).get(user_id=auth.user_id))


@router.put("/profile", response_model=ProfileResponse)
def put_profile(body: ProfileUpdate, auth: Auth, session: DbSession) -> ProfileResponse:
    return to_response(ProfileService(session).replace(user_id=auth.user_id, data=body))
