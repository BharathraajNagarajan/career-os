import re
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker
from starlette.routing import Route

from tests.auth.fake_idp import FakeIdentityProvider
from tests.db.auth_helpers import Persona, make_persona, new_client
from tests.db.llm_helpers import VALID, make_gateway, structured
from tests.db.resume_helpers import create_lane, upload
from tests.db.review_helpers import create_item
from tests.synthetic import synthetic_pdf

pytestmark = pytest.mark.db

Route_ = tuple[str, str]

A_HEADLINE = "Persona A headline"
A_LABEL = "Persona A resume"
A_LANE = "Persona A lane"

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
    a_ids: dict[str, str]


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


def assert_a_profile_unchanged(personas: Personas) -> None:
    body = personas.a.client.get("/api/v1/profile").json()
    assert body["headline"] == A_HEADLINE


def a_resume(personas: Personas) -> dict[str, Any]:
    resumes = personas.a.client.get("/api/v1/resumes").json()
    assert len(resumes) == 1
    body: dict[str, Any] = resumes[0]
    return body


def assert_a_resume_untouched(personas: Personas) -> None:
    resume = a_resume(personas)
    assert resume["id"] == personas.a_ids["resume"]
    assert resume["label"] == A_LABEL
    assert resume["status"] == "active"
    assert resume["lane_id"] == personas.a_ids["lane"]


def assert_a_lane_untouched(personas: Personas) -> None:
    lanes = personas.a.client.get("/api/v1/lanes").json()
    assert [(lane["id"], lane["name"], lane["status"]) for lane in lanes] == [
        (personas.a_ids["lane"], A_LANE, "active")
    ]
    assert_a_resume_untouched(personas)


A_BUDGET_SPENT = "a_budget_spent"
REVIEW_ITEMS = "/api/v1/review-items"
REVIEW_FOREIGN = lambda personas: {"item_id": personas.a_ids["review"]}  # noqa: E731
REVIEW_BODY = {"expected_state_version": 1}


def assert_a_budget_untouched(personas: Personas) -> None:
    body = personas.a.client.get("/api/v1/llm/budget").json()
    assert body["spent_usd"] == personas.a_ids[A_BUDGET_SPENT]


def assert_a_review_item_untouched(personas: Personas) -> None:
    body = personas.a.client.get(f"{REVIEW_ITEMS}/{personas.a_ids['review']}").json()
    assert body["status"] == "pending"
    assert body["state_version"] == 1
    assert body["decided_at"] is None
    assert personas.a.client.get("/api/v1/profile").json()["headline"] == A_HEADLINE


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
    ("GET", "/api/v1/profile"): IsolationCase(
        "/api/v1/profile", a_untouched=assert_a_profile_unchanged
    ),
    ("PUT", "/api/v1/profile"): IsolationCase(
        "/api/v1/profile",
        body={"headline": "Overwritten by persona B"},
        a_untouched=assert_a_profile_unchanged,
    ),
    ("POST", "/api/v1/resumes"): IsolationCase(
        "/api/v1/resumes", a_untouched=assert_a_resume_untouched
    ),
    ("GET", "/api/v1/resumes"): IsolationCase(
        "/api/v1/resumes",
        list_ids=lambda body: {row["id"] for row in body},
        a_foreign_ids=lambda personas: {personas.a_ids["resume"]},
    ),
    ("GET", "/api/v1/resumes/{resume_id}"): IsolationCase(
        "/api/v1/resumes/{resume_id}",
        foreign_params=lambda personas: {"resume_id": personas.a_ids["resume"]},
        a_untouched=assert_a_resume_untouched,
    ),
    ("PATCH", "/api/v1/resumes/{resume_id}"): IsolationCase(
        "/api/v1/resumes/{resume_id}",
        body={"label": "hijacked", "lane_id": None},
        foreign_params=lambda personas: {"resume_id": personas.a_ids["resume"]},
        a_untouched=assert_a_resume_untouched,
    ),
    ("POST", "/api/v1/resumes/{resume_id}/archive"): IsolationCase(
        "/api/v1/resumes/{resume_id}/archive",
        foreign_params=lambda personas: {"resume_id": personas.a_ids["resume"]},
        a_untouched=assert_a_resume_untouched,
    ),
    ("POST", "/api/v1/resumes/{resume_id}/unarchive"): IsolationCase(
        "/api/v1/resumes/{resume_id}/unarchive",
        foreign_params=lambda personas: {"resume_id": personas.a_ids["resume"]},
        a_untouched=assert_a_resume_untouched,
    ),
    ("GET", "/api/v1/resumes/{resume_id}/file"): IsolationCase(
        "/api/v1/resumes/{resume_id}/file",
        foreign_params=lambda personas: {"resume_id": personas.a_ids["resume"]},
        a_untouched=assert_a_resume_untouched,
    ),
    ("GET", "/api/v1/lanes"): IsolationCase(
        "/api/v1/lanes",
        list_ids=lambda body: {row["id"] for row in body},
        a_foreign_ids=lambda personas: {personas.a_ids["lane"]},
    ),
    ("POST", "/api/v1/lanes"): IsolationCase(
        "/api/v1/lanes",
        body={"name": "Persona B lane"},
        a_untouched=assert_a_lane_untouched,
    ),
    ("PATCH", "/api/v1/lanes/{lane_id}"): IsolationCase(
        "/api/v1/lanes/{lane_id}",
        body={"name": "hijacked", "default_resume_id": None},
        foreign_params=lambda personas: {"lane_id": personas.a_ids["lane"]},
        a_untouched=assert_a_lane_untouched,
    ),
    ("POST", "/api/v1/lanes/{lane_id}/archive"): IsolationCase(
        "/api/v1/lanes/{lane_id}/archive",
        foreign_params=lambda personas: {"lane_id": personas.a_ids["lane"]},
        a_untouched=assert_a_lane_untouched,
    ),
    ("POST", "/api/v1/lanes/{lane_id}/unarchive"): IsolationCase(
        "/api/v1/lanes/{lane_id}/unarchive",
        foreign_params=lambda personas: {"lane_id": personas.a_ids["lane"]},
        a_untouched=assert_a_lane_untouched,
    ),
    ("GET", "/api/v1/llm/budget"): IsolationCase(
        "/api/v1/llm/budget", a_untouched=assert_a_budget_untouched
    ),
    ("GET", REVIEW_ITEMS): IsolationCase(
        REVIEW_ITEMS,
        list_ids=lambda body: {row["id"] for row in body},
        a_foreign_ids=lambda personas: {personas.a_ids["review"]},
    ),
    ("GET", REVIEW_ITEMS + "/{item_id}"): IsolationCase(
        REVIEW_ITEMS + "/{item_id}",
        foreign_params=REVIEW_FOREIGN,
        a_untouched=assert_a_review_item_untouched,
    ),
    ("POST", REVIEW_ITEMS + "/{item_id}/confirm"): IsolationCase(
        REVIEW_ITEMS + "/{item_id}/confirm",
        body=REVIEW_BODY,
        foreign_params=REVIEW_FOREIGN,
        a_untouched=assert_a_review_item_untouched,
    ),
    ("POST", REVIEW_ITEMS + "/{item_id}/edit-confirm"): IsolationCase(
        REVIEW_ITEMS + "/{item_id}/edit-confirm",
        body={**REVIEW_BODY, "payload": {"schema_version": 1, "name": "hijacked"}},
        foreign_params=REVIEW_FOREIGN,
        a_untouched=assert_a_review_item_untouched,
    ),
    ("POST", REVIEW_ITEMS + "/{item_id}/reject"): IsolationCase(
        REVIEW_ITEMS + "/{item_id}/reject",
        body=REVIEW_BODY,
        foreign_params=REVIEW_FOREIGN,
        a_untouched=assert_a_review_item_untouched,
    ),
    ("POST", "/api/v1/account/deletion"): IsolationCase(
        "/api/v1/account/deletion",
        body={"confirm": "DELETE MY ACCOUNT"},
        a_untouched=assert_a_has_session_and_active_status,
    ),
}


def seed(persona: Persona, *, label: str, headline: str, lane: str) -> dict[str, str]:
    lane_row = create_lane(persona, lane)
    resume = upload(
        persona, synthetic_pdf(f"isolation-{persona.label}"), lane_id=lane_row["id"], label=label
    ).json()
    persona.request("PUT", "/api/v1/profile", json={"headline": headline})
    return {"lane": lane_row["id"], "resume": resume["id"]}


@pytest.fixture
def personas(
    app: FastAPI,
    idp: FakeIdentityProvider,
    owner_session: Session,
    app_sessions: sessionmaker[Session],
) -> Personas:
    a = make_persona(app, idp, "a")
    b = make_persona(app, idp, "b")
    a_ids = seed(a, label=A_LABEL, headline=A_HEADLINE, lane=A_LANE)
    seed(b, label="Persona B resume", headline="Persona B headline", lane="Persona B seeded lane")
    for owner_persona in (a, b):
        gateway, _ = make_gateway(app_sessions, script=[VALID])
        structured(gateway, owner_persona.user_id)
    registry = app.state.review_registry
    a_ids["review"] = str(create_item(app_sessions, registry, a.user_id, name="Persona A skill"))
    create_item(app_sessions, registry, b.user_id, name="Persona B skill")
    a_ids[A_BUDGET_SPENT] = a.client.get("/api/v1/llm/budget").json()["spent_usd"]
    return Personas(a, b, owner_session, a_ids)


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
    return {name: str(uuid.uuid4()) for name in re.findall(r"{(\w+)}", case.path)}


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
