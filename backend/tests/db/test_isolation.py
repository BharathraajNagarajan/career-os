import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.routing import Route

from tests.auth.fake_idp import FakeIdentityProvider
from tests.db.auth_helpers import Persona, make_persona, new_client

pytestmark = pytest.mark.db

Route_ = tuple[str, str]

PUBLIC: set[Route_] = {
    ("GET", "/healthz"),
    ("GET", "/api/v1/auth/google/start"),
    ("GET", "/api/v1/auth/google/callback"),
    ("GET", "/openapi.json"),
    ("GET", "/docs"),
    ("GET", "/docs/oauth2-redirect"),
}


@dataclass(frozen=True)
class Personas:
    a: Persona
    b: Persona
    owner: Session


@dataclass(frozen=True)
class IsolationCase:
    path: str
    body: dict[str, Any] | None = None
    foreign_params: Callable[[Personas], dict[str, str]] | None = None
    list_ids: Callable[[Any], set[str]] | None = None
    a_foreign_ids: Callable[[Personas], set[str]] | None = None
    a_untouched: Callable[[Personas], None] = field(default=lambda _: None)


def assert_a_still_signed_in(personas: Personas) -> None:
    assert personas.a.client.get("/api/v1/auth/me").status_code == 200
    assert personas.a.client.get("/api/v1/auth/me").json()["id"] == str(personas.a.user_id)


def assert_a_has_session_and_active_status(personas: Personas) -> None:
    personas.owner.rollback()
    status: str = personas.owner.execute(
        text("SELECT status FROM users WHERE id = :id"), {"id": personas.a.user_id}
    ).scalar_one()
    assert status == "active"
    assert_a_still_signed_in(personas)


PROTECTED: dict[Route_, IsolationCase] = {
    ("GET", "/api/v1/auth/me"): IsolationCase(
        "/api/v1/auth/me",
        a_untouched=assert_a_still_signed_in,
    ),
    ("GET", "/api/v1/auth/sessions"): IsolationCase(
        "/api/v1/auth/sessions",
        list_ids=lambda body: {row["id"] for row in body},
        a_foreign_ids=lambda personas: {str(personas.a.session_id)},
    ),
    ("POST", "/api/v1/auth/logout"): IsolationCase(
        "/api/v1/auth/logout", a_untouched=assert_a_still_signed_in
    ),
    ("DELETE", "/api/v1/auth/sessions/{session_id}"): IsolationCase(
        "/api/v1/auth/sessions/{session_id}",
        foreign_params=lambda personas: {"session_id": str(personas.a.session_id)},
        a_untouched=assert_a_still_signed_in,
    ),
    ("POST", "/api/v1/account/deletion"): IsolationCase(
        "/api/v1/account/deletion",
        body={"confirm": "DELETE MY ACCOUNT"},
        a_untouched=assert_a_has_session_and_active_status,
    ),
}


@pytest.fixture
def personas(app: FastAPI, idp: FakeIdentityProvider, owner_session: Session) -> Personas:
    return Personas(make_persona(app, idp, "a"), make_persona(app, idp, "b"), owner_session)


HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def registered_routes(app: FastAPI) -> set[Route_]:
    found: set[Route_] = set()
    for route in app.routes:
        if isinstance(route, Route):
            found.update(
                (method, route.path) for method in route.methods or set() if method != "HEAD"
            )
    for path, operations in app.openapi()["paths"].items():
        found.update((method.upper(), path) for method in operations if method in HTTP_METHODS)
    return found


def hidden_routes(routes: Iterable[Any]) -> list[str]:
    hidden: list[str] = []
    for route in routes:
        nested = getattr(route, "original_router", None)
        if nested is not None:
            hidden.extend(hidden_routes(nested.routes))
        elif isinstance(route, APIRoute) and not route.include_in_schema:
            hidden.append(route.path)
    return hidden


def render(case: IsolationCase, params: dict[str, str]) -> str:
    return case.path.format(**params) if params else case.path


def sample_params(case: IsolationCase) -> dict[str, str]:
    return {"session_id": str(uuid.uuid4())} if "{session_id}" in case.path else {}


def test_every_registered_route_is_classified(app: FastAPI) -> None:
    registered = registered_routes(app)
    classified = PUBLIC | set(PROTECTED)

    assert registered - classified == set(), "route without an isolation classification"
    assert classified - registered == set(), "classification for a route that does not exist"
    assert PUBLIC.isdisjoint(PROTECTED)
    assert hidden_routes(app.routes) == [], "routes hidden from the schema escape the harness"


def test_a_new_route_without_a_classification_is_detected(app: FastAPI) -> None:
    @app.get("/api/v1/future-resource/{item_id}")
    def future_resource(item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    unclassified = registered_routes(app) - (PUBLIC | set(PROTECTED))

    assert unclassified == {("GET", "/api/v1/future-resource/{item_id}")}


@pytest.mark.parametrize("route", sorted(PROTECTED))
def test_protected_route_without_a_session_is_unauthorized(app: FastAPI, route: Route_) -> None:
    case = PROTECTED[route]

    response = new_client(app).request(route[0], render(case, sample_params(case)), json=case.body)

    assert response.status_code == 401


@pytest.mark.parametrize(
    "route", sorted(route for route, case in PROTECTED.items() if case.foreign_params)
)
def test_foreign_resource_ids_are_not_found(personas: Personas, route: Route_) -> None:
    case = PROTECTED[route]
    assert case.foreign_params is not None

    response = personas.b.request(
        route[0], render(case, case.foreign_params(personas)), json=case.body
    )

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found"}}
    case.a_untouched(personas)


@pytest.mark.parametrize(
    "route", sorted(route for route, case in PROTECTED.items() if case.list_ids)
)
def test_list_endpoints_never_return_another_users_rows(personas: Personas, route: Route_) -> None:
    case = PROTECTED[route]
    assert case.list_ids is not None
    assert case.a_foreign_ids is not None

    response = personas.b.request(route[0], case.path)

    assert response.status_code == 200
    ids = case.list_ids(response.json())
    assert ids
    assert ids.isdisjoint(case.a_foreign_ids(personas))


@pytest.mark.parametrize("route", sorted(PROTECTED))
def test_acting_as_one_user_never_changes_another_users_state(
    personas: Personas, route: Route_
) -> None:
    case = PROTECTED[route]
    params = case.foreign_params(personas) if case.foreign_params else sample_params(case)

    personas.b.request(route[0], render(case, params), json=case.body)

    case.a_untouched(personas)
