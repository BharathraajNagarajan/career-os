from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.auth.cookies import SESSION_COOKIE, SESSION_COOKIE_DELETIONS
from app.auth.google import GoogleIdentityProvider
from app.auth.oidc import IdentityProvider
from app.auth.service import AuthContext, AuthenticationFailed, AuthService
from app.auth.tokens import csrf_token, values_equal
from app.config import AuthSettings, get_auth_settings
from app.core.errors import ApiError

CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def get_db_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def get_identity_provider(
    request: Request, settings: Annotated[AuthSettings, Depends(get_auth_settings)]
) -> IdentityProvider:
    provider: IdentityProvider | None = request.app.state.identity_provider
    if provider is None:
        provider = GoogleIdentityProvider(settings)
        request.app.state.identity_provider = provider
    return provider


def get_auth_service(
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
) -> AuthService:
    return AuthService(session, settings)


def _authenticate(request: Request, service: AuthService) -> AuthContext:
    cached: AuthContext | None = getattr(request.state, "auth_context", None)
    if cached is not None:
        return cached
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise ApiError(401, "unauthenticated")
    try:
        context = service.authenticate(token)
    except AuthenticationFailed as exc:
        raise ApiError(
            401,
            "unauthenticated",
            delete_cookies=SESSION_COOKIE_DELETIONS if exc.clear_cookies else (),
        ) from exc
    request.state.auth_context = context
    return context


def current_auth(
    request: Request, service: Annotated[AuthService, Depends(get_auth_service)]
) -> AuthContext:
    return _authenticate(request, service)


def verify_csrf(
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
) -> None:
    if request.method in SAFE_METHODS:
        return
    context = _authenticate(request, service)
    supplied = request.headers.get(CSRF_HEADER)
    expected = csrf_token(settings.session_secret, context.session_id)
    if not supplied or not values_equal(supplied, expected):
        raise ApiError(403, "csrf_failed")
