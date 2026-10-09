import json
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.applications.events import ApplicationNoted
from app.events.payloads import payload_registry
from tests.auth.fake_idp import FakeIdentityProvider
from tests.db.application_helpers import applied, current, entry_for, new_opportunity, timeline
from tests.db.auth_helpers import Persona, make_persona
from tests.db.contact_helpers import (
    INTERACTIONS,
    body_of,
    create_company,
    create_contact,
    create_interaction,
    error_code,
    future,
)
from tests.db.opportunity_helpers import rows, scalar

pytestmark = pytest.mark.db


@pytest.fixture
def persona(app: FastAPI, idp: FakeIdentityProvider) -> Persona:
    return make_persona(app, idp, "a")


@pytest.fixture
def other(app: FastAPI, idp: FakeIdentityProvider) -> Persona:
    return make_persona(app, idp, "b")


def interaction_count(owner: Session) -> int:
    return int(scalar(owner, "SELECT count(*) FROM interactions"))


def application_events(owner: Session, application_id: str) -> list[Any]:
    return rows(
        owner,
        "SELECT event_type, payload, occurred_at FROM domain_events "
        "WHERE aggregate_type = 'application' AND aggregate_id = :id ORDER BY recorded_at, id",
        id=application_id,
    )


def test_an_interaction_is_recorded_on_any_channel_and_direction(persona: Persona) -> None:
    contact = create_contact(persona)

    for channel in ("email", "linkedin", "phone", "in_person", "other"):
        for direction in ("inbound", "outbound"):
            body = body_of(
                create_interaction(persona, contact["id"], channel=channel, direction=direction),
                201,
            )
            assert (body["channel"], body["direction"]) == (channel, direction)
            assert body["application_state_version"] is None

    listed = body_of_list(
        persona.request("GET", INTERACTIONS, params={"contact_id": contact["id"]})
    )
    assert len(listed) == 10


def body_of_list(response: Any) -> list[dict[str, Any]]:
    assert response.status_code == 200, response.text
    body: list[dict[str, Any]] = response.json()
    return body


def test_occurred_at_may_be_backdated_but_not_far_in_the_future(
    persona: Persona, owner_session: Session
) -> None:
    contact = create_contact(persona)

    assert (
        create_interaction(persona, contact["id"], occurred_at=future(days=-400)).status_code == 201
    )
    assert create_interaction(persona, contact["id"], occurred_at=future(4)).status_code == 201
    late = create_interaction(persona, contact["id"], occurred_at=future(10))
    assert (late.status_code, error_code(late)) == (422, "occurred_at_in_future")
    assert interaction_count(owner_session) == 2


def test_summary_is_stored_as_plain_text_and_bounded(persona: Persona) -> None:
    contact = create_contact(persona)
    hostile = "<script>alert(1)</script> Alex & co\r\n  line two  "

    stored = body_of(create_interaction(persona, contact["id"], summary=hostile), 201)

    assert stored["summary"] == "<script>alert(1)</script> Alex & co\n  line two"
    assert create_interaction(persona, contact["id"], summary="x" * 2000).status_code == 201
    assert create_interaction(persona, contact["id"], summary="x" * 2001).status_code == 422
    blank = body_of(create_interaction(persona, contact["id"], summary="   "), 201)
    assert blank["summary"] is None


def test_list_filters_and_get(persona: Persona) -> None:
    first = create_contact(persona, "Alex Example")
    second = create_contact(persona, "Sam Example")
    opportunity, application = applied(persona, "interaction filters")
    one = body_of(create_interaction(persona, first["id"], occurred_at=future(-30)), 201)
    two = body_of(create_interaction(persona, second["id"], opportunity_id=opportunity["id"]), 201)
    three = body_of(
        create_interaction(persona, second["id"], application_id=application["id"]), 201
    )

    def ids(**params: str) -> list[str]:
        return [
            item["id"] for item in body_of_list(persona.request("GET", INTERACTIONS, params=params))
        ]

    assert ids() == [three["id"], two["id"], one["id"]]
    assert ids(contact_id=first["id"]) == [one["id"]]
    assert ids(opportunity_id=opportunity["id"]) == [three["id"], two["id"]]
    assert ids(application_id=application["id"]) == [three["id"]]
    assert body_of(persona.request("GET", f"{INTERACTIONS}/{one['id']}"))["id"] == one["id"]
    assert persona.request("GET", f"{INTERACTIONS}/{uuid.uuid4()}").status_code == 404


def test_an_application_fills_in_its_opportunity_and_company(persona: Persona) -> None:
    contact = create_contact(persona)
    opportunity, application = applied(persona, "interaction derives")
    company = create_company(persona, "Derived Corp")
    body_of(
        persona.request(
            "PATCH",
            f"/api/v1/opportunities/{opportunity['id']}",
            json={
                "expected_state_version": opportunity["state_version"],
                "company_id": company["id"],
            },
        )
    )

    stored = body_of(
        create_interaction(persona, contact["id"], application_id=application["id"]), 201
    )

    assert stored["opportunity_id"] == opportunity["id"]
    assert stored["company_id"] == company["id"]


def test_an_application_must_belong_to_the_named_opportunity(persona: Persona) -> None:
    contact = create_contact(persona)
    _, application = applied(persona, "interaction mismatch")
    unrelated = new_opportunity(persona, "interaction unrelated")

    response = create_interaction(
        persona, contact["id"], application_id=application["id"], opportunity_id=unrelated["id"]
    )

    assert (response.status_code, error_code(response)) == (422, "application_opportunity_mismatch")


def test_an_application_event_is_recorded_with_the_interaction(
    persona: Persona, owner_session: Session
) -> None:
    contact = create_contact(persona)
    opportunity, application = applied(persona, "interaction event")
    occurred = future(-60)

    stored = body_of(
        create_interaction(
            persona,
            contact["id"],
            channel="linkedin",
            summary="Sent a note",
            occurred_at=occurred,
            application_id=application["id"],
            application_event_type="OUTREACH_SENT",
            expected_application_state_version=application["state_version"],
        ),
        201,
    )

    after = current(persona, application)
    assert after["state_version"] == application["state_version"] + 1
    assert stored["application_state_version"] == after["state_version"]
    assert after["stage"] == "applied"
    events = application_events(owner_session, application["id"])
    assert [event.event_type for event in events] == ["APPLICATION_SUBMITTED", "OUTREACH_SENT"]
    payload = events[-1].payload
    assert payload["schema_version"] == 2
    assert payload["interaction_id"] == stored["id"]
    assert events[-1].occurred_at.isoformat() == stored["occurred_at"].replace("Z", "+00:00")
    entries = timeline(persona, opportunity["id"])
    shown = entry_for(entries, "INTERACTION")
    assert (shown["interaction_channel"], shown["interaction_direction"]) == (
        "linkedin",
        "outbound",
    )
    assert shown["note"] == "Sent a note"
    assert shown["voidable"] is False
    assert entry_for(entries, "OUTREACH_SENT")["voidable"] is True


@pytest.mark.parametrize(
    "event_type",
    [
        "OUTREACH_SENT",
        "FOLLOWUP_SENT",
        "RECRUITER_CONTACTED",
        "CONTACT_REPLIED",
        "CONNECTION_REQUEST_SENT",
        "CONNECTION_ACCEPTED",
    ],
)
def test_every_allowed_event_type_is_recordable(persona: Persona, event_type: str) -> None:
    contact = create_contact(persona)
    _, application = applied(persona, f"allowed {event_type}")

    response = create_interaction(
        persona,
        contact["id"],
        application_id=application["id"],
        application_event_type=event_type,
        expected_application_state_version=application["state_version"],
    )

    assert response.status_code == 201, response.text
    assert current(persona, application)["stage"] == "applied"


@pytest.mark.parametrize(
    "event_type", ["REJECTED", "OFFER_RECEIVED", "INTERVIEW_SCHEDULED", "WITHDRAWN", "EVENT_VOIDED"]
)
def test_stage_bearing_and_internal_events_are_refused(
    persona: Persona, owner_session: Session, event_type: str
) -> None:
    contact = create_contact(persona)
    _, application = applied(persona, f"refused {event_type}")

    response = create_interaction(
        persona,
        contact["id"],
        application_id=application["id"],
        application_event_type=event_type,
        expected_application_state_version=application["state_version"],
    )

    assert response.status_code == 422
    assert interaction_count(owner_session) == 0
    assert current(persona, application)["state_version"] == application["state_version"]


def test_an_event_needs_an_application_and_an_expected_version(
    persona: Persona, owner_session: Session
) -> None:
    contact = create_contact(persona)
    _, application = applied(persona, "event prerequisites")

    no_application = create_interaction(
        persona, contact["id"], application_event_type="OUTREACH_SENT"
    )
    no_version = create_interaction(
        persona,
        contact["id"],
        application_id=application["id"],
        application_event_type="OUTREACH_SENT",
    )

    assert (no_application.status_code, error_code(no_application)) == (422, "application_required")
    assert no_version.status_code == 422
    assert interaction_count(owner_session) == 0


def test_a_stale_application_version_writes_nothing(
    persona: Persona, owner_session: Session
) -> None:
    contact = create_contact(persona)
    _, application = applied(persona, "stale interaction")
    body_of(
        persona.request(
            "POST",
            f"/api/v1/applications/{application['id']}/events",
            json={
                "expected_state_version": application["state_version"],
                "event_type": "NOTE_ADDED",
                "occurred_at": future(-1),
            },
        )
    )
    before = len(application_events(owner_session, application["id"]))

    stale = create_interaction(
        persona,
        contact["id"],
        application_id=application["id"],
        application_event_type="OUTREACH_SENT",
        expected_application_state_version=application["state_version"],
    )

    assert (stale.status_code, error_code(stale)) == (409, "conflict")
    assert interaction_count(owner_session) == 0
    assert len(application_events(owner_session, application["id"])) == before


def test_foreign_references_are_not_found_and_write_nothing(
    persona: Persona, other: Persona, owner_session: Session
) -> None:
    mine = create_contact(persona)
    theirs = create_contact(other, "Sam Example")
    foreign_opportunity, foreign_application = applied(other, "foreign interaction")

    cases = (
        {"contact_id": theirs["id"]},
        {"contact_id": mine["id"], "opportunity_id": foreign_opportunity["id"]},
        {"contact_id": mine["id"], "application_id": foreign_application["id"]},
    )
    for case in cases:
        contact_id = case.pop("contact_id")
        assert create_interaction(persona, contact_id, **case).status_code == 404

    assert interaction_count(owner_session) == 0
    assert (
        scalar(
            owner_session, "SELECT count(*) FROM domain_events WHERE event_type = 'OUTREACH_SENT'"
        )
        == 0
    )


def test_a_version_1_note_payload_still_loads_and_shows_in_the_timeline(
    persona: Persona, owner_session: Session
) -> None:
    opportunity, application = applied(persona, "version one payload")
    legacy = {
        "schema_version": 1,
        "application_id": application["id"],
        "note": "Written before interactions existed",
    }
    owner_session.execute(
        text(
            "INSERT INTO domain_events (id, user_id, aggregate_type, aggregate_id, event_type, "
            "occurred_at, actor, payload) SELECT :id, user_id, 'application', id, 'NOTE_ADDED', "
            "now(), 'user', CAST(:payload AS jsonb) FROM applications WHERE id = :application"
        ),
        {"id": uuid.uuid4(), "payload": json.dumps(legacy), "application": application["id"]},
    )
    owner_session.commit()

    entries = timeline(persona, opportunity["id"])

    assert entry_for(entries, "NOTE_ADDED")["note"] == "Written before interactions existed"
    loaded = payload_registry.load("NOTE_ADDED", legacy)
    assert isinstance(loaded, ApplicationNoted)
    assert (loaded.schema_version, loaded.interaction_id) == (2, None)
