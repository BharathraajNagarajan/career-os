import pytest
from fastapi import FastAPI

from tests.auth.fake_idp import FakeIdentityProvider
from tests.db.auth_helpers import make_persona, new_client

pytestmark = pytest.mark.db


def test_mutation_without_token_is_forbidden(app: FastAPI, idp: FakeIdentityProvider) -> None:
    persona = make_persona(app, idp, "a")

    response = persona.client.post("/api/v1/auth/logout")

    assert response.status_code == 403
    assert response.json() == {"error": {"code": "csrf_failed"}}
    assert persona.client.get("/api/v1/auth/me").status_code == 200


def test_mutation_with_wrong_token_is_forbidden(app: FastAPI, idp: FakeIdentityProvider) -> None:
    persona = make_persona(app, idp, "a")

    response = persona.client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "wrong"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"


def test_token_from_another_session_is_forbidden(app: FastAPI, idp: FakeIdentityProvider) -> None:
    victim = make_persona(app, idp, "a")
    attacker = make_persona(app, idp, "b")
    foreign = attacker.client.cookies["career_os_csrf"]

    response = victim.client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": foreign})

    assert response.status_code == 403
    assert victim.client.get("/api/v1/auth/me").status_code == 200


def test_matching_token_is_accepted(app: FastAPI, idp: FakeIdentityProvider) -> None:
    persona = make_persona(app, idp, "a")

    assert persona.request("POST", "/api/v1/auth/logout").status_code == 204


def test_reads_do_not_need_a_token(app: FastAPI, idp: FakeIdentityProvider) -> None:
    persona = make_persona(app, idp, "a")

    assert persona.client.get("/api/v1/auth/sessions").status_code == 200


def test_unauthenticated_mutation_is_unauthorized_not_forbidden(app: FastAPI) -> None:
    response = new_client(app).post("/api/v1/auth/logout", headers={"X-CSRF-Token": "anything"})

    assert response.status_code == 401
