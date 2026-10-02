import hashlib
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.auth.preauth import PREAUTH_COOKIE
from app.config import AuthSettings, Settings, get_auth_settings
from app.main import create_app
from tests.auth.fake_idp import FakeIdentityProvider
from tests.db.auth_helpers import new_client, sign_in, start_sign_in

pytestmark = pytest.mark.db

EMAIL = "persona-a@example.test"


def count(owner: Session, table: str) -> int:
    queries = {
        "users": "SELECT count(*) FROM users",
        "auth_identities": "SELECT count(*) FROM auth_identities",
        "sessions": "SELECT count(*) FROM sessions",
    }
    value: int = owner.execute(text(queries[table])).scalar_one()
    return value


def set_cookie_headers(response: httpx2.Response) -> list[str]:
    return response.headers.get_list("set-cookie")


def test_start_redirects_to_provider_with_pkce_and_identity_scopes(
    app: FastAPI, idp: FakeIdentityProvider
) -> None:
    client = new_client(app)

    state, response = start_sign_in(client, idp, return_to="/settings")
    query = parse_qs(urlparse(response.headers["location"]).query)

    assert response.status_code == 302
    assert query["scope"] == ["openid email profile"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"] == [state]
    assert "gmail" not in response.headers["location"]


def test_start_sets_encrypted_scoped_preauth_cookie(
    app: FastAPI, idp: FakeIdentityProvider
) -> None:
    client = new_client(app)

    state, response = start_sign_in(client, idp)
    cookie = next(item for item in set_cookie_headers(response) if PREAUTH_COOKIE in item)

    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/api/v1/auth" in cookie
    assert "Max-Age=600" in cookie
    assert state not in cookie
    assert idp.pending[state].nonce not in cookie


@pytest.mark.parametrize("target", ["https://evil.example", "//evil.example", "/\\evil", "x", ""])
def test_start_rejects_unsafe_return_paths(app: FastAPI, target: str) -> None:
    response = new_client(app).get("/api/v1/auth/google/start", params={"return_to": target})

    assert response.status_code == 400
    assert response.json() == {"error": {"code": "invalid_return_to"}}


def test_successful_sign_in_creates_user_identity_and_hashed_session(
    app: FastAPI, idp: FakeIdentityProvider, owner_session: Session
) -> None:
    client = new_client(app)

    response = sign_in(client, idp, subject="sub-a", email=EMAIL, return_to="/settings")

    assert response.status_code == 302
    assert response.headers["location"] == "http://localhost:5173/settings"
    assert count(owner_session, "users") == 1
    assert count(owner_session, "auth_identities") == 1
    assert count(owner_session, "sessions") == 1
    cookie_value = client.cookies["career_os_session"]
    stored: bytes = owner_session.execute(text("SELECT token_hash FROM sessions")).scalar_one()
    assert bytes(stored) == hashlib.sha256(cookie_value.encode()).digest()
    assert bytes(stored) != cookie_value.encode()


def test_session_and_csrf_cookie_flags(app: FastAPI, idp: FakeIdentityProvider) -> None:
    client = new_client(app)

    response = sign_in(client, idp, subject="sub-a", email=EMAIL)
    headers = set_cookie_headers(response)
    session_cookie = next(item for item in headers if item.startswith("career_os_session="))
    csrf_cookie = next(item for item in headers if item.startswith("career_os_csrf="))
    preauth_cookie = next(item for item in headers if item.startswith(f"{PREAUTH_COOKIE}="))

    assert "HttpOnly" in session_cookie
    assert "SameSite=lax" in session_cookie
    assert "Path=/" in session_cookie
    assert "Max-Age=2592000" in session_cookie
    assert "Domain" not in session_cookie
    assert "HttpOnly" not in csrf_cookie
    assert "SameSite=lax" in csrf_cookie
    assert "Max-Age=0" in preauth_cookie


def test_me_returns_the_signed_in_user(app: FastAPI, idp: FakeIdentityProvider) -> None:
    client = new_client(app)
    sign_in(client, idp, subject="sub-a", email=EMAIL, name="Persona A")

    body = client.get("/api/v1/auth/me").json()

    assert body["primary_email"] == EMAIL
    assert body["display_name"] == "Persona A"
    assert body["status"] == "active"


def test_repeat_sign_in_reuses_user_and_rotates_the_session(
    app: FastAPI, idp: FakeIdentityProvider, owner_session: Session
) -> None:
    client = new_client(app)
    sign_in(client, idp, subject="sub-a", email=EMAIL)
    first_token = client.cookies["career_os_session"]

    sign_in(client, idp, subject="sub-a", email=EMAIL)

    assert client.cookies["career_os_session"] != first_token
    assert count(owner_session, "users") == 1
    assert count(owner_session, "auth_identities") == 1
    assert count(owner_session, "sessions") == 2


def test_missing_preauth_cookie_is_rejected(app: FastAPI, idp: FakeIdentityProvider) -> None:
    client = new_client(app)
    state, _ = start_sign_in(client, idp)
    code = idp.issue_code(state, subject="sub-a", email=EMAIL)
    client.cookies.clear()

    response = client.get("/api/v1/auth/google/callback", params={"code": code, "state": state})

    assert response.headers["location"] == "http://localhost:5173/sign-in?error=invalid_state"
    assert "career_os_session" not in client.cookies


def test_state_mismatch_is_rejected(app: FastAPI, idp: FakeIdentityProvider) -> None:
    client = new_client(app)
    state, _ = start_sign_in(client, idp)
    code = idp.issue_code(state, subject="sub-a", email=EMAIL)

    response = client.get(
        "/api/v1/auth/google/callback", params={"code": code, "state": "forged-state"}
    )

    assert response.headers["location"].endswith("error=invalid_state")


def test_provider_error_parameter_is_rejected_with_generic_code(app: FastAPI) -> None:
    client = new_client(app)

    response = client.get(
        "/api/v1/auth/google/callback", params={"error": "access_denied: secret details"}
    )

    assert response.headers["location"] == "http://localhost:5173/sign-in?error=idp_error"


def test_preauth_cookie_is_single_use(app: FastAPI, idp: FakeIdentityProvider) -> None:
    client = new_client(app)
    state, _ = start_sign_in(client, idp)
    code = idp.issue_code(state, subject="sub-a", email=EMAIL)
    first = client.get("/api/v1/auth/google/callback", params={"code": code, "state": state})
    replay_code = idp.issue_code(state, subject="sub-a", email=EMAIL)

    replay = client.get(
        "/api/v1/auth/google/callback", params={"code": replay_code, "state": state}
    )

    assert first.headers["location"] == "http://localhost:5173/"
    assert replay.headers["location"].endswith("error=invalid_state")


@pytest.mark.parametrize(
    "overrides",
    [
        {"nonce": "attacker-nonce"},
        {"email_verified": False},
        {"aud": "another-client"},
        {"iss": "https://evil.example"},
        {"exp": 1, "iat": 0},
    ],
)
def test_invalid_id_tokens_do_not_sign_in(
    app: FastAPI, idp: FakeIdentityProvider, owner_session: Session, overrides: dict[str, Any]
) -> None:
    client = new_client(app)

    response = sign_in(client, idp, subject="sub-a", email=EMAIL, **overrides)

    assert response.headers["location"] == "http://localhost:5173/sign-in?error=sign_in_failed"
    assert count(owner_session, "users") == 0
    assert count(owner_session, "sessions") == 0


def test_existing_email_without_identity_is_a_conflict(
    app: FastAPI, idp: FakeIdentityProvider, owner_session: Session
) -> None:
    owner_session.execute(
        text("INSERT INTO users (id, primary_email) VALUES (gen_random_uuid(), :email)"),
        {"email": EMAIL.upper()},
    )
    owner_session.commit()

    response = sign_in(new_client(app), idp, subject="sub-new", email=EMAIL)

    assert response.headers["location"] == "http://localhost:5173/sign-in?error=account_conflict"
    assert count(owner_session, "auth_identities") == 0
    assert count(owner_session, "sessions") == 0


def test_deletion_requested_user_cannot_sign_in(
    app: FastAPI, idp: FakeIdentityProvider, owner_session: Session
) -> None:
    sign_in(new_client(app), idp, subject="sub-a", email=EMAIL)
    owner_session.execute(text("UPDATE users SET status = 'deletion_requested'"))
    owner_session.commit()

    response = sign_in(new_client(app), idp, subject="sub-a", email=EMAIL)

    assert response.headers["location"] == "http://localhost:5173/sign-in?error=account_unavailable"
    assert count(owner_session, "sessions") == 1


def test_sign_in_succeeds_after_the_provider_rotates_its_signing_key(
    db_settings: Settings,
    app_sessions: sessionmaker[Session],
    auth_settings: AuthSettings,
    owner_session: Session,
) -> None:
    rotating = FakeIdentityProvider()
    application = create_app(db_settings, session_factory=app_sessions, identity_provider=rotating)
    application.dependency_overrides[get_auth_settings] = lambda: auth_settings
    rotating.key = rotating.rotate_key()

    response = sign_in(new_client(application), rotating, subject="sub-a", email=EMAIL)

    assert response.headers["location"] == "http://localhost:5173/"
    assert rotating.refresh_count == 1
    assert count(owner_session, "sessions") == 1
