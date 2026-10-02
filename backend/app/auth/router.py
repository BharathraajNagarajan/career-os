import uuid
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.auth.cookies import clear_session_cookies, set_session_cookies
from app.auth.deps import current_auth, get_auth_service, get_identity_provider, verify_csrf
from app.auth.oidc import IdentityProvider, OidcError, verify_id_token
from app.auth.preauth import PREAUTH_COOKIE, PREAUTH_PATH, PreAuth, seal, unseal
from app.auth.service import AuthContext, AuthService, SignInError
from app.auth.tokens import csrf_token, new_random_value, values_equal
from app.config import AuthSettings, get_auth_settings
from app.core.errors import ApiError, ErrorResponse
from app.core.logging import get_logger
from app.db.models import UserStatus

log = get_logger(__name__)

MAX_RETURN_TO_LENGTH = 512
PREAUTH_MAX_AGE = 600

router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(verify_csrf)],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)

Service = Annotated[AuthService, Depends(get_auth_service)]
Settings = Annotated[AuthSettings, Depends(get_auth_settings)]
Provider = Annotated[IdentityProvider, Depends(get_identity_provider)]
Auth = Annotated[AuthContext, Depends(current_auth)]


class MeResponse(BaseModel):
    id: uuid.UUID
    primary_email: str
    display_name: str | None
    status: UserStatus


class SessionResponse(BaseModel):
    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    current: bool


class DeletionRequest(BaseModel):
    confirm: Literal["DELETE MY ACCOUNT"]


def safe_return_to(value: str) -> str:
    if (
        not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
        or len(value) > MAX_RETURN_TO_LENGTH
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ApiError(400, "invalid_return_to")
    return value


def _sign_in_failure(settings: AuthSettings, code: str) -> RedirectResponse:
    log.info("sign_in_rejected", error_code=code)
    response = RedirectResponse(
        f"{settings.app_base_url.rstrip('/')}/sign-in?error={quote(code)}", status_code=302
    )
    response.delete_cookie(PREAUTH_COOKIE, path=PREAUTH_PATH)
    return response


@router.get("/auth/google/start", status_code=302, response_class=RedirectResponse)
def google_start(settings: Settings, provider: Provider, return_to: str = "/") -> RedirectResponse:
    target = safe_return_to(return_to)
    pre = PreAuth(
        state=new_random_value(),
        nonce=new_random_value(),
        code_verifier=new_random_value(),
        return_to=target,
    )
    try:
        url = provider.authorization_url(
            state=pre.state, nonce=pre.nonce, code_verifier=pre.code_verifier
        )
    except OidcError as exc:
        return _sign_in_failure(settings, exc.code)
    response = RedirectResponse(url, status_code=302)
    response.set_cookie(
        PREAUTH_COOKIE,
        seal(settings.session_secret, pre),
        max_age=PREAUTH_MAX_AGE,
        path=PREAUTH_PATH,
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/auth/google/callback", status_code=302, response_class=RedirectResponse)
def google_callback(
    request: Request,
    settings: Settings,
    provider: Provider,
    service: Service,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    pre = unseal(settings.session_secret, request.cookies.get(PREAUTH_COOKIE))
    if error is not None:
        return _sign_in_failure(settings, "idp_error")
    if pre is None or not state or not code or not values_equal(state, pre.state):
        return _sign_in_failure(settings, "invalid_state")
    try:
        id_token = provider.exchange_code(code=code, code_verifier=pre.code_verifier)
        identity = verify_id_token(id_token, provider=provider, nonce=pre.nonce)
    except OidcError as exc:
        log.info("sign_in_rejected", error_code=exc.code)
        return _sign_in_failure(settings, "sign_in_failed")
    try:
        issued = service.sign_in(identity, user_agent=request.headers.get("user-agent"))
    except SignInError as exc:
        return _sign_in_failure(settings, exc.code)
    response = RedirectResponse(
        f"{settings.app_base_url.rstrip('/')}{pre.return_to}", status_code=302
    )
    set_session_cookies(
        response,
        settings,
        token=issued.token,
        csrf=csrf_token(settings.session_secret, issued.session_id),
    )
    response.delete_cookie(PREAUTH_COOKIE, path=PREAUTH_PATH)
    return response


@router.post("/auth/logout", status_code=204)
def logout(auth: Auth, service: Service) -> Response:
    service.revoke(user_id=auth.user_id, session_id=auth.session_id)
    response = Response(status_code=204)
    clear_session_cookies(response)
    return response


@router.get("/auth/me", response_model=MeResponse)
def me(auth: Auth, service: Service) -> MeResponse:
    user = service.get_user(auth.user_id)
    if user is None:
        raise ApiError(401, "unauthenticated")
    return MeResponse(
        id=user.id,
        primary_email=user.primary_email,
        display_name=user.display_name,
        status=user.status,
    )


@router.get("/auth/sessions", response_model=list[SessionResponse])
def list_sessions(auth: Auth, service: Service) -> list[SessionResponse]:
    return [
        SessionResponse(
            id=row.id,
            created_at=row.created_at,
            last_seen_at=row.last_seen_at,
            expires_at=row.expires_at,
            current=row.id == auth.session_id,
        )
        for row in service.list_sessions(user_id=auth.user_id)
    ]


@router.delete(
    "/auth/sessions/{session_id}",
    status_code=204,
    responses={404: {"model": ErrorResponse}},
)
def revoke_session(session_id: uuid.UUID, auth: Auth, service: Service) -> Response:
    service.revoke(user_id=auth.user_id, session_id=session_id)
    response = Response(status_code=204)
    if session_id == auth.session_id:
        clear_session_cookies(response)
    return response


@router.post("/account/deletion", status_code=202)
def request_account_deletion(body: DeletionRequest, auth: Auth, service: Service) -> Response:
    service.request_deletion(user_id=auth.user_id)
    response = Response(status_code=202)
    clear_session_cookies(response)
    return response
