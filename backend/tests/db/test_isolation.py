import re
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
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
from tests.db.opportunity_helpers import jd_variant
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


A_OPPORTUNITY_TITLE = "Persona A opportunity title"
A_COMPANY = "Persona A company"
A_QUALIFICATION = "Persona A qualification line"
OPPORTUNITIES = "/api/v1/opportunities"
COMPANIES = "/api/v1/companies"
QUALIFICATIONS = "/api/v1/qualifications"


def opportunity_foreign(personas: Personas) -> dict[str, str]:
    return {"opportunity_id": personas.a_ids["opportunity"]}


def qualification_foreign(personas: Personas) -> dict[str, str]:
    return {"qualification_id": personas.a_ids["qualification"]}


def company_foreign(personas: Personas) -> dict[str, str]:
    return {"company_id": personas.a_ids["company"]}


def assert_a_opportunity_untouched(personas: Personas) -> None:
    listed = personas.a.client.get(OPPORTUNITIES).json()
    assert {row["id"] for row in listed} == {
        personas.a_ids["opportunity"],
        personas.a_ids["applied_opportunity"],
    }
    body = personas.a.client.get(f"{OPPORTUNITIES}/{personas.a_ids['opportunity']}").json()
    assert body["title"] == A_OPPORTUNITY_TITLE
    assert body["priority"] == "normal"
    assert body["status"] == "new"
    assert body["allowed_actions"] == ["save", "skip", "apply", "close"]
    assert body["extraction_status"] == "pending"
    assert body["state_version"] == int(personas.a_ids["opportunity_version"])
    assert body["company"] is None
    assert [item["text_verbatim"] for item in body["qualifications"]] == [A_QUALIFICATION]
    assert [item["id"] for item in body["qualifications"]] == [personas.a_ids["qualification"]]
    duplicates = personas.a.client.get(
        f"{OPPORTUNITIES}/{personas.a_ids['opportunity']}/duplicates"
    ).json()
    assert duplicates == []
    assert_a_company_untouched(personas)


def assert_a_company_untouched(personas: Personas) -> None:
    companies = personas.a.client.get(COMPANIES).json()
    assert len(companies) == 2
    by_id = {row["id"]: (row["name"], row["strategic_priority"]) for row in companies}
    assert by_id[personas.a_ids["company"]] == (A_COMPANY, "normal")


APPLICATIONS = "/api/v1/applications"
A_APPLICATION_NOTE = "Persona A application note"
EVENT_BODY = {
    "expected_state_version": 1,
    "event_type": "NOTE_ADDED",
    "occurred_at": "2026-01-01T00:00:00Z",
    "note": "planted by persona b",
}


def application_foreign(personas: Personas) -> dict[str, str]:
    return {"application_id": personas.a_ids["application"]}


def event_foreign(personas: Personas) -> dict[str, str]:
    return {
        "application_id": personas.a_ids["application"],
        "event_id": personas.a_ids["application_event"],
    }


def assert_a_application_untouched(personas: Personas) -> None:
    listed = personas.a.client.get(APPLICATIONS).json()
    assert [row["id"] for row in listed] == [personas.a_ids["application"]]
    body = personas.a.client.get(f"{APPLICATIONS}/{personas.a_ids['application']}").json()
    assert body["stage"] == "assessment"
    assert body["is_terminal"] is False
    assert body["state_version"] == int(personas.a_ids["application_version"])
    timeline = personas.a.client.get(
        f"{OPPORTUNITIES}/{personas.a_ids['applied_opportunity']}/timeline"
    ).json()
    assert [entry["voided"] for entry in timeline].count(True) == 0
    assert [entry["note"] for entry in timeline if entry["note"]] == [A_APPLICATION_NOTE]
    assert len(timeline) == int(personas.a_ids["timeline_length"])


CONTACTS = "/api/v1/contacts"
INTERACTIONS = "/api/v1/interactions"
ACTIONS = "/api/v1/actions"
RULES = "/api/v1/strategy-rules"
A_CONTACT_NAME = "Persona A contact"
A_CONTACT_EMAIL = "persona-a-contact@example.test"
A_INTERACTION_SUMMARY = "Persona A interaction summary"
A_ACTION_TITLE = "Persona A action title"
A_RULE_STATEMENT = "Persona A rule statement"
STALE_STAMP = "2026-01-01T00:00:00Z"


def contact_foreign(personas: Personas) -> dict[str, str]:
    return {"contact_id": personas.a_ids["contact"]}


def contact_company_foreign(personas: Personas) -> dict[str, str]:
    return {"contact_id": personas.a_ids["contact"], "company_id": personas.a_ids["company"]}


def contact_opportunity_foreign(personas: Personas) -> dict[str, str]:
    return {
        "contact_id": personas.a_ids["contact"],
        "opportunity_id": personas.a_ids["opportunity"],
    }


def merge_foreign(personas: Personas) -> dict[str, str]:
    return {"survivor_id": personas.a_ids["contact"]}


def interaction_foreign(personas: Personas) -> dict[str, str]:
    return {"interaction_id": personas.a_ids["interaction"]}


def action_foreign(personas: Personas) -> dict[str, str]:
    return {"action_id": personas.a_ids["action"]}


def rule_foreign(personas: Personas) -> dict[str, str]:
    return {"rule_id": personas.a_ids["rule"]}


def assert_a_contact_untouched(personas: Personas) -> None:
    listed = personas.a.client.get(CONTACTS).json()
    assert [row["id"] for row in listed] == [personas.a_ids["contact"]]
    body = personas.a.client.get(f"{CONTACTS}/{personas.a_ids['contact']}").json()
    assert body["full_name"] == A_CONTACT_NAME
    assert body["headline"] is None
    assert [item["address"] for item in body["emails"]] == [A_CONTACT_EMAIL]
    assert body["updated_at"] == personas.a_ids["contact_updated_at"]
    assert body["companies"] == []
    assert body["opportunities"] == []
    assert [item["summary"] for item in body["interactions"]] == [A_INTERACTION_SUMMARY]
    assert [item["title"] for item in body["actions"]] == [A_ACTION_TITLE]


def assert_a_interaction_untouched(personas: Personas) -> None:
    listed = personas.a.client.get(INTERACTIONS).json()
    assert [(row["id"], row["summary"]) for row in listed] == [
        (personas.a_ids["interaction"], A_INTERACTION_SUMMARY)
    ]
    assert_a_contact_untouched(personas)


def assert_a_action_untouched(personas: Personas) -> None:
    listed = personas.a.client.get(ACTIONS).json()
    assert [(row["id"], row["title"], row["status"]) for row in listed] == [
        (personas.a_ids["action"], A_ACTION_TITLE, "open")
    ]
    assert listed[0]["state_version"] == int(personas.a_ids["action_version"])


def assert_a_rule_untouched(personas: Personas) -> None:
    listed = personas.a.client.get(RULES).json()
    assert [(row["id"], row["statement"], row["active"]) for row in listed] == [
        (personas.a_ids["rule"], A_RULE_STATEMENT, True)
    ]


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
    ("POST", OPPORTUNITIES + "/ingest"): IsolationCase(
        OPPORTUNITIES + "/ingest",
        body={"jd_text": jd_variant("persona b ingest")},
        a_untouched=assert_a_opportunity_untouched,
    ),
    ("GET", OPPORTUNITIES): IsolationCase(
        OPPORTUNITIES,
        list_ids=lambda body: {row["id"] for row in body},
        a_foreign_ids=lambda personas: {
            personas.a_ids["opportunity"],
            personas.a_ids["applied_opportunity"],
        },
    ),
    ("GET", OPPORTUNITIES + "/{opportunity_id}"): IsolationCase(
        OPPORTUNITIES + "/{opportunity_id}",
        foreign_params=opportunity_foreign,
        a_untouched=assert_a_opportunity_untouched,
    ),
    ("PATCH", OPPORTUNITIES + "/{opportunity_id}"): IsolationCase(
        OPPORTUNITIES + "/{opportunity_id}",
        body={"expected_state_version": 1, "title": "hijacked"},
        foreign_params=opportunity_foreign,
        a_untouched=assert_a_opportunity_untouched,
    ),
    ("PATCH", OPPORTUNITIES + "/{opportunity_id}/priority"): IsolationCase(
        OPPORTUNITIES + "/{opportunity_id}/priority",
        body={"priority": "high"},
        foreign_params=opportunity_foreign,
        a_untouched=assert_a_opportunity_untouched,
    ),
    ("POST", OPPORTUNITIES + "/{opportunity_id}/extract"): IsolationCase(
        OPPORTUNITIES + "/{opportunity_id}/extract",
        foreign_params=opportunity_foreign,
        a_untouched=assert_a_opportunity_untouched,
    ),
    ("GET", OPPORTUNITIES + "/{opportunity_id}/duplicates"): IsolationCase(
        OPPORTUNITIES + "/{opportunity_id}/duplicates",
        foreign_params=opportunity_foreign,
        a_untouched=assert_a_opportunity_untouched,
    ),
    ("POST", OPPORTUNITIES + "/{opportunity_id}/qualifications"): IsolationCase(
        OPPORTUNITIES + "/{opportunity_id}/qualifications",
        body={"kind": "minimum", "text_verbatim": "planted", "category": "skill"},
        foreign_params=opportunity_foreign,
        a_untouched=assert_a_opportunity_untouched,
    ),
    ("PATCH", QUALIFICATIONS + "/{qualification_id}"): IsolationCase(
        QUALIFICATIONS + "/{qualification_id}",
        body={"kind": "preferred"},
        foreign_params=qualification_foreign,
        a_untouched=assert_a_opportunity_untouched,
    ),
    ("DELETE", QUALIFICATIONS + "/{qualification_id}"): IsolationCase(
        QUALIFICATIONS + "/{qualification_id}",
        foreign_params=qualification_foreign,
        a_untouched=assert_a_opportunity_untouched,
    ),
    ("GET", COMPANIES): IsolationCase(
        COMPANIES,
        list_ids=lambda body: {row["id"] for row in body},
        a_foreign_ids=lambda personas: {personas.a_ids["company"]},
    ),
    ("GET", COMPANIES + "/{company_id}"): IsolationCase(
        COMPANIES + "/{company_id}",
        foreign_params=company_foreign,
        a_untouched=assert_a_company_untouched,
    ),
    ("POST", COMPANIES): IsolationCase(
        COMPANIES,
        body={"name": "Persona B company"},
        a_untouched=assert_a_company_untouched,
    ),
    ("PATCH", COMPANIES + "/{company_id}"): IsolationCase(
        COMPANIES + "/{company_id}",
        body={"name": "hijacked", "strategic_priority": "high"},
        foreign_params=company_foreign,
        a_untouched=assert_a_company_untouched,
    ),
    ("POST", OPPORTUNITIES + "/{opportunity_id}/save"): IsolationCase(
        OPPORTUNITIES + "/{opportunity_id}/save",
        body={"expected_state_version": 1},
        foreign_params=opportunity_foreign,
        a_untouched=assert_a_opportunity_untouched,
    ),
    ("POST", OPPORTUNITIES + "/{opportunity_id}/skip"): IsolationCase(
        OPPORTUNITIES + "/{opportunity_id}/skip",
        body={"expected_state_version": 1, "reason": "planted"},
        foreign_params=opportunity_foreign,
        a_untouched=assert_a_opportunity_untouched,
    ),
    ("POST", OPPORTUNITIES + "/{opportunity_id}/close"): IsolationCase(
        OPPORTUNITIES + "/{opportunity_id}/close",
        body={"expected_state_version": 1},
        foreign_params=opportunity_foreign,
        a_untouched=assert_a_opportunity_untouched,
    ),
    ("POST", OPPORTUNITIES + "/{opportunity_id}/apply"): IsolationCase(
        OPPORTUNITIES + "/{opportunity_id}/apply",
        body={"expected_state_version": 1},
        foreign_params=opportunity_foreign,
        a_untouched=assert_a_opportunity_untouched,
    ),
    ("GET", OPPORTUNITIES + "/{opportunity_id}/timeline"): IsolationCase(
        OPPORTUNITIES + "/{opportunity_id}/timeline",
        foreign_params=lambda personas: {"opportunity_id": personas.a_ids["applied_opportunity"]},
        a_untouched=assert_a_application_untouched,
    ),
    ("GET", APPLICATIONS): IsolationCase(
        APPLICATIONS,
        list_ids=lambda body: {row["id"] for row in body},
        a_foreign_ids=lambda personas: {personas.a_ids["application"]},
    ),
    ("GET", APPLICATIONS + "/{application_id}"): IsolationCase(
        APPLICATIONS + "/{application_id}",
        foreign_params=application_foreign,
        a_untouched=assert_a_application_untouched,
    ),
    ("POST", APPLICATIONS + "/{application_id}/events"): IsolationCase(
        APPLICATIONS + "/{application_id}/events",
        body=EVENT_BODY,
        foreign_params=application_foreign,
        a_untouched=assert_a_application_untouched,
    ),
    ("POST", APPLICATIONS + "/{application_id}/events/{event_id}/void"): IsolationCase(
        APPLICATIONS + "/{application_id}/events/{event_id}/void",
        body={"expected_state_version": 1},
        foreign_params=event_foreign,
        a_untouched=assert_a_application_untouched,
    ),
    ("POST", APPLICATIONS + "/{application_id}/reopen"): IsolationCase(
        APPLICATIONS + "/{application_id}/reopen",
        body={"expected_state_version": 1},
        foreign_params=application_foreign,
        a_untouched=assert_a_application_untouched,
    ),
    ("GET", CONTACTS): IsolationCase(
        CONTACTS,
        list_ids=lambda body: {row["id"] for row in body},
        a_foreign_ids=lambda personas: {personas.a_ids["contact"]},
    ),
    ("POST", CONTACTS): IsolationCase(
        CONTACTS,
        body={"full_name": "Persona B contact", "emails": [A_CONTACT_EMAIL]},
        a_untouched=assert_a_contact_untouched,
    ),
    ("GET", CONTACTS + "/{contact_id}"): IsolationCase(
        CONTACTS + "/{contact_id}",
        foreign_params=contact_foreign,
        a_untouched=assert_a_contact_untouched,
    ),
    ("PATCH", CONTACTS + "/{contact_id}"): IsolationCase(
        CONTACTS + "/{contact_id}",
        body={"expected_updated_at": STALE_STAMP, "headline": "hijacked"},
        foreign_params=contact_foreign,
        a_untouched=assert_a_contact_untouched,
    ),
    ("POST", CONTACTS + "/{contact_id}/companies/{company_id}"): IsolationCase(
        CONTACTS + "/{contact_id}/companies/{company_id}",
        body={"relation": "recruiter"},
        foreign_params=contact_company_foreign,
        a_untouched=assert_a_contact_untouched,
    ),
    ("DELETE", CONTACTS + "/{contact_id}/companies/{company_id}"): IsolationCase(
        CONTACTS + "/{contact_id}/companies/{company_id}",
        foreign_params=contact_company_foreign,
        a_untouched=assert_a_contact_untouched,
    ),
    ("POST", CONTACTS + "/{contact_id}/opportunities/{opportunity_id}"): IsolationCase(
        CONTACTS + "/{contact_id}/opportunities/{opportunity_id}",
        body={"role": "recruiter"},
        foreign_params=contact_opportunity_foreign,
        a_untouched=assert_a_contact_untouched,
    ),
    ("DELETE", CONTACTS + "/{contact_id}/opportunities/{opportunity_id}"): IsolationCase(
        CONTACTS + "/{contact_id}/opportunities/{opportunity_id}?role=recruiter",
        foreign_params=contact_opportunity_foreign,
        a_untouched=assert_a_contact_untouched,
    ),
    ("POST", CONTACTS + "/{survivor_id}/merge"): IsolationCase(
        CONTACTS + "/{survivor_id}/merge",
        body={
            "merged_id": "00000000-0000-4000-8000-000000000001",
            "expected_survivor_updated_at": STALE_STAMP,
            "expected_merged_updated_at": STALE_STAMP,
        },
        foreign_params=merge_foreign,
        a_untouched=assert_a_contact_untouched,
    ),
    ("GET", INTERACTIONS): IsolationCase(
        INTERACTIONS,
        list_ids=lambda body: {row["id"] for row in body},
        a_foreign_ids=lambda personas: {personas.a_ids["interaction"]},
    ),
    ("GET", INTERACTIONS + "/{interaction_id}"): IsolationCase(
        INTERACTIONS + "/{interaction_id}",
        foreign_params=interaction_foreign,
        a_untouched=assert_a_interaction_untouched,
    ),
    ("POST", INTERACTIONS): IsolationCase(
        INTERACTIONS,
        body={
            "contact_id": "00000000-0000-4000-8000-000000000001",
            "channel": "email",
            "direction": "outbound",
            "occurred_at": STALE_STAMP,
        },
        a_untouched=assert_a_interaction_untouched,
    ),
    ("GET", ACTIONS): IsolationCase(
        ACTIONS,
        list_ids=lambda body: {row["id"] for row in body},
        a_foreign_ids=lambda personas: {personas.a_ids["action"]},
    ),
    ("GET", ACTIONS + "/{action_id}"): IsolationCase(
        ACTIONS + "/{action_id}",
        foreign_params=action_foreign,
        a_untouched=assert_a_action_untouched,
    ),
    ("POST", ACTIONS): IsolationCase(
        ACTIONS,
        body={"kind": "custom", "title": "Persona B action"},
        a_untouched=assert_a_action_untouched,
    ),
    ("PATCH", ACTIONS + "/{action_id}"): IsolationCase(
        ACTIONS + "/{action_id}",
        body={"expected_state_version": 1, "title": "hijacked"},
        foreign_params=action_foreign,
        a_untouched=assert_a_action_untouched,
    ),
    ("POST", ACTIONS + "/{action_id}/snooze"): IsolationCase(
        ACTIONS + "/{action_id}/snooze",
        body={"expected_state_version": 1, "until": "2099-01-01T00:00:00Z"},
        foreign_params=action_foreign,
        a_untouched=assert_a_action_untouched,
    ),
    ("POST", ACTIONS + "/{action_id}/complete"): IsolationCase(
        ACTIONS + "/{action_id}/complete",
        body={"expected_state_version": 1},
        foreign_params=action_foreign,
        a_untouched=assert_a_action_untouched,
    ),
    ("POST", ACTIONS + "/{action_id}/dismiss"): IsolationCase(
        ACTIONS + "/{action_id}/dismiss",
        body={"expected_state_version": 1},
        foreign_params=action_foreign,
        a_untouched=assert_a_action_untouched,
    ),
    ("GET", RULES): IsolationCase(
        RULES,
        list_ids=lambda body: {row["id"] for row in body},
        a_foreign_ids=lambda personas: {personas.a_ids["rule"]},
    ),
    ("POST", RULES): IsolationCase(
        RULES,
        body={"scope": "global", "statement": "Persona B rule", "rule_type": "preference"},
        a_untouched=assert_a_rule_untouched,
    ),
    ("PATCH", RULES + "/{rule_id}"): IsolationCase(
        RULES + "/{rule_id}",
        body={"statement": "hijacked", "active": False},
        foreign_params=rule_foreign,
        a_untouched=assert_a_rule_untouched,
    ),
    ("DELETE", RULES + "/{rule_id}"): IsolationCase(
        RULES + "/{rule_id}",
        foreign_params=rule_foreign,
        a_untouched=assert_a_rule_untouched,
    ),
    ("POST", "/api/v1/account/deletion"): IsolationCase(
        "/api/v1/account/deletion",
        body={"confirm": "DELETE MY ACCOUNT"},
        a_untouched=assert_a_has_session_and_active_status,
    ),
}


def seed_opportunity(
    persona: Persona, *, title: str, company: str, line: str, variant: str = ""
) -> dict[str, str]:
    opportunity = persona.request(
        "POST",
        OPPORTUNITIES + "/ingest",
        json={"jd_text": jd_variant(f"seed {persona.label}{variant}")},
    ).json()
    persona.request(
        "PATCH",
        f"{OPPORTUNITIES}/{opportunity['id']}",
        json={"expected_state_version": opportunity["state_version"], "title": title},
    )
    created = persona.request(
        "POST",
        f"{OPPORTUNITIES}/{opportunity['id']}/qualifications",
        json={"kind": "minimum", "text_verbatim": line, "category": "skill"},
    ).json()
    company_row = persona.request("POST", COMPANIES, json={"name": company}).json()
    detail = persona.request("GET", f"{OPPORTUNITIES}/{opportunity['id']}").json()
    return {
        "opportunity": opportunity["id"],
        "opportunity_version": str(detail["state_version"]),
        "qualification": created["id"],
        "company": company_row["id"],
    }


def seed_application(persona: Persona, a_ids: dict[str, str]) -> dict[str, str]:
    other = seed_opportunity(
        persona,
        title=f"Persona {persona.label.upper()} applied title",
        company=f"Persona {persona.label.upper()} applied company",
        line=f"Persona {persona.label.upper()} applied line",
        variant=" applied",
    )
    applied = persona.request(
        "POST",
        f"{OPPORTUNITIES}/{other['opportunity']}/apply",
        json={
            "expected_state_version": int(other["opportunity_version"]),
            "resume_id": a_ids["resume"],
            "lane_id": a_ids["lane"],
        },
    ).json()["application"]
    recorded = persona.request(
        "POST",
        f"{APPLICATIONS}/{applied['id']}/events",
        json={
            "expected_state_version": applied["state_version"],
            "event_type": "ASSESSMENT_RECEIVED",
            "occurred_at": datetime.now(UTC).isoformat(),
            "note": A_APPLICATION_NOTE,
        },
    ).json()
    timeline = persona.request("GET", f"{OPPORTUNITIES}/{other['opportunity']}/timeline").json()
    event = next(entry for entry in timeline if entry["event_type"] == "ASSESSMENT_RECEIVED")
    return {
        "applied_opportunity": other["opportunity"],
        "application": applied["id"],
        "application_version": str(recorded["state_version"]),
        "application_event": event["id"],
        "timeline_length": str(len(timeline)),
    }


def seed_relationships(persona: Persona, *, tag: str) -> dict[str, str]:
    name = A_CONTACT_NAME if tag == "a" else f"Persona {tag.upper()} contact"
    email = A_CONTACT_EMAIL if tag == "a" else f"persona-{tag}-contact@example.test"
    contact = persona.request("POST", CONTACTS, json={"full_name": name, "emails": [email]}).json()
    interaction = persona.request(
        "POST",
        INTERACTIONS,
        json={
            "contact_id": contact["id"],
            "channel": "email",
            "direction": "outbound",
            "occurred_at": datetime.now(UTC).isoformat(),
            "summary": A_INTERACTION_SUMMARY if tag == "a" else f"Persona {tag} summary",
        },
    ).json()
    action = persona.request(
        "POST",
        ACTIONS,
        json={
            "kind": "custom",
            "title": A_ACTION_TITLE if tag == "a" else f"Persona {tag} action",
            "contact_id": contact["id"],
        },
    ).json()
    rule = persona.request(
        "POST",
        RULES,
        json={
            "scope": "global",
            "statement": A_RULE_STATEMENT if tag == "a" else f"Persona {tag} rule",
            "rule_type": "preference",
        },
    ).json()
    return {
        "contact": contact["id"],
        "contact_updated_at": contact["updated_at"],
        "interaction": interaction["id"],
        "action": action["id"],
        "action_version": str(action["state_version"]),
        "rule": rule["id"],
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
    b_ids = seed(
        b, label="Persona B resume", headline="Persona B headline", lane="Persona B seeded lane"
    )
    a_ids.update(
        seed_opportunity(a, title=A_OPPORTUNITY_TITLE, company=A_COMPANY, line=A_QUALIFICATION)
    )
    a_ids.update(seed_application(a, a_ids))
    seed_opportunity(
        b, title="Persona B title", company="Persona B seeded company", line="Persona B line"
    )
    seed_application(b, b_ids)
    a_ids.update(seed_relationships(a, tag="a"))
    seed_relationships(b, tag="b")
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
