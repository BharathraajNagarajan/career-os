import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.tokens import csrf_token
from app.config import AuthSettings
from tests.auth.fake_idp import FakeIdentityProvider
from tests.db.auth_helpers import Persona, make_persona, new_client, sign_in

pytestmark = pytest.mark.db


def age_session(owner: Session, session_id: uuid.UUID, **columns: datetime) -> None:
    assignments = {
        "last_seen_at": "UPDATE sessions SET last_seen_at = :value WHERE id = :id",
        "expires_at": "UPDATE sessions SET expires_at = :value WHERE id = :id",
    }
    for column, value in columns.items():
        owner.execute(text(assignments[column]), {"value": value, "id": session_id})
    owner.commit()


def session_count(owner: Session) -> int:
    value: int = owner.execute(text("SELECT count(*) FROM sessions")).scalar_one()
    return value


def test_no_cookie_is_unauthenticated(app: FastAPI) -> None:
    response = new_client(app).get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json() == {"error": {"code": "unauthenticated"}}


def test_unknown_token_is_unauthenticated(app: FastAPI) -> None:
    client = new_client(app)
    client.cookies.set("career_os_session", "not-a-real-token", domain="localhost")

    assert client.get("/api/v1/auth/me").status_code == 401


def test_idle_session_is_rejected_deleted_and_cookies_cleared(
    app: FastAPI, idp: FakeIdentityProvider, owner_session: Session
) -> None:
    persona = make_persona(app, idp, "a")
    stale = datetime.now(UTC) - timedelta(hours=169)
    age_session(owner_session, persona.session_id, last_seen_at=stale)

    response = persona.client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert any(
        "career_os_session=" in item and "Max-Age=0" in item
        for item in response.headers.get_list("set-cookie")
    )
    assert session_count(owner_session) == 0


def test_absolute_expiry_is_enforced_even_when_recently_active(
    app: FastAPI, idp: FakeIdentityProvider, owner_session: Session
) -> None:
    persona = make_persona(app, idp, "a")
    age_session(
        owner_session, persona.session_id, expires_at=datetime.now(UTC) - timedelta(seconds=1)
    )

    assert persona.client.get("/api/v1/auth/me").status_code == 401
    assert session_count(owner_session) == 0


def test_session_of_a_user_pending_deletion_is_rejected(
    app: FastAPI, idp: FakeIdentityProvider, owner_session: Session
) -> None:
    persona = make_persona(app, idp, "a")
    owner_session.execute(text("UPDATE users SET status = 'deletion_requested'"))
    owner_session.commit()

    assert persona.client.get("/api/v1/auth/me").status_code == 401
    assert session_count(owner_session) == 0


def test_last_seen_is_refreshed_only_after_five_minutes(
    app: FastAPI, idp: FakeIdentityProvider, owner_session: Session
) -> None:
    persona = make_persona(app, idp, "a")
    recent = datetime.now(UTC) - timedelta(minutes=1)
    age_session(owner_session, persona.session_id, last_seen_at=recent)

    persona.client.get("/api/v1/auth/me")
    unchanged: datetime = owner_session.execute(
        text("SELECT last_seen_at FROM sessions")
    ).scalar_one()
    older = datetime.now(UTC) - timedelta(minutes=10)
    age_session(owner_session, persona.session_id, last_seen_at=older)
    owner_session.expire_all()
    persona.client.get("/api/v1/auth/me")
    refreshed: datetime = owner_session.execute(
        text("SELECT last_seen_at FROM sessions")
    ).scalar_one()

    assert unchanged == recent
    assert refreshed > older + timedelta(minutes=9)


def test_logout_deletes_the_session_and_clears_cookies(
    app: FastAPI, idp: FakeIdentityProvider, owner_session: Session
) -> None:
    persona = make_persona(app, idp, "a")

    response = persona.request("POST", "/api/v1/auth/logout")

    assert response.status_code == 204
    assert session_count(owner_session) == 0
    assert persona.client.get("/api/v1/auth/me").status_code == 401


def test_sessions_list_shows_only_own_sessions_without_secrets(
    app: FastAPI, idp: FakeIdentityProvider
) -> None:
    first = make_persona(app, idp, "a")
    sign_in(first.client, idp, subject="subject-a", email="persona-a@example.test")
    other = make_persona(app, idp, "b")

    rows = first.client.get("/api/v1/auth/sessions").json()

    assert len(rows) == 2
    assert sum(row["current"] for row in rows) == 1
    assert other.session_id not in {uuid.UUID(row["id"]) for row in rows}
    assert set(rows[0]) == {"id", "created_at", "last_seen_at", "expires_at", "current"}


def test_user_can_revoke_another_of_their_own_sessions(
    app: FastAPI, idp: FakeIdentityProvider, owner_session: Session
) -> None:
    first = make_persona(app, idp, "a")
    second_client = new_client(app)
    sign_in(second_client, idp, subject="subject-a", email="persona-a@example.test")
    second = Persona(second_client, first.user_id, uuid.uuid4(), "a")
    rows = first.client.get("/api/v1/auth/sessions").json()
    other_id = next(row["id"] for row in rows if not row["current"])

    response = first.request("DELETE", f"/api/v1/auth/sessions/{other_id}")

    assert response.status_code == 204
    assert session_count(owner_session) == 1
    assert second.client.get("/api/v1/auth/me").status_code == 401
    assert first.client.get("/api/v1/auth/me").status_code == 200


def test_revoking_the_current_session_clears_cookies(
    app: FastAPI, idp: FakeIdentityProvider
) -> None:
    persona = make_persona(app, idp, "a")

    response = persona.request("DELETE", f"/api/v1/auth/sessions/{persona.session_id}")

    assert response.status_code == 204
    assert persona.client.get("/api/v1/auth/me").status_code == 401


def test_revoking_another_users_session_is_not_found(
    app: FastAPI, idp: FakeIdentityProvider, owner_session: Session
) -> None:
    owner_a = make_persona(app, idp, "a")
    intruder = make_persona(app, idp, "b")

    response = intruder.request("DELETE", f"/api/v1/auth/sessions/{owner_a.session_id}")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found"}}
    assert session_count(owner_session) == 2
    assert owner_a.client.get("/api/v1/auth/me").status_code == 200


def test_csrf_token_is_bound_to_the_session(
    app: FastAPI, idp: FakeIdentityProvider, auth_settings: AuthSettings
) -> None:
    persona = make_persona(app, idp, "a")

    assert persona.client.cookies["career_os_csrf"] == csrf_token(
        auth_settings.session_secret, persona.session_id
    )
