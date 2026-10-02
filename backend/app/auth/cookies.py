from fastapi import Response

from app.config import AuthSettings

SESSION_COOKIE = "career_os_session"
CSRF_COOKIE = "career_os_csrf"
SESSION_COOKIE_DELETIONS = ((SESSION_COOKIE, "/"), (CSRF_COOKIE, "/"))


def set_session_cookies(
    response: Response, settings: AuthSettings, *, token: str, csrf: str
) -> None:
    max_age = int(settings.session_absolute_timeout_hours * 3600)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=max_age,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=False,
        samesite="lax",
    )


def clear_session_cookies(response: Response) -> None:
    for name, path in SESSION_COOKIE_DELETIONS:
        response.delete_cookie(name, path=path)
