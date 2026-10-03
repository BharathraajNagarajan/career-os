import logging
import random
import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.state_machines.application import ApplicationEventType
from tests.auth.fake_idp import FakeIdentityProvider
from tests.db.application_helpers import (
    APPLICATIONS,
    OPPORTUNITIES,
    applied,
    apply_to,
    current,
    decide,
    entry_for,
    error_code,
    new_opportunity,
    record,
    reopen,
    stored_state,
    timeline,
    void,
    when,
)
from tests.db.auth_helpers import Persona, make_persona
from tests.db.opportunity_helpers import get_opportunity, row, rows, scalar
from tests.db.resume_helpers import create_lane, upload
from tests.synthetic import synthetic_pdf

pytestmark = pytest.mark.db


@pytest.fixture
def persona(app: FastAPI, idp: FakeIdentityProvider) -> Persona:
    return make_persona(app, idp, "a")


@pytest.fixture
def other(app: FastAPI, idp: FakeIdentityProvider) -> Persona:
    return make_persona(app, idp, "b")


def decisions(owner: Session, opportunity_id: str) -> list[Any]:
    return rows(
        owner,
        "SELECT event_type, actor, payload, correlation_id, occurred_at FROM domain_events "
        "WHERE aggregate_type = 'opportunity' AND aggregate_id = :id "
        "AND event_type = 'OPPORTUNITY_DECIDED' ORDER BY recorded_at, id",
        id=opportunity_id,
    )


def test_a_new_opportunity_offers_every_decision(persona: Persona) -> None:
    opportunity = new_opportunity(persona, "fresh")

    assert opportunity["status"] == "new"
    assert opportunity["allowed_actions"] == ["save", "skip", "apply", "close"]


def test_save_skip_reconsider_and_close_follow_the_table(
    persona: Persona, owner_session: Session
) -> None:
    opportunity = new_opportunity(persona, "walk")
    content_updated_at = scalar(
        owner_session,
        "SELECT content_updated_at FROM opportunities WHERE id = :id",
        id=opportunity["id"],
    )

    saved = decide(persona, opportunity, "save", reason="looks promising")
    assert saved.status_code == 200
    assert saved.json()["status"] == "saved"
    assert saved.json()["allowed_actions"] == ["skip", "apply", "close"]
    assert saved.json()["state_version"] == opportunity["state_version"] + 1

    skipped = decide(persona, saved.json(), "skip", reason="  too far  ")
    assert skipped.json()["status"] == "skipped"
    assert skipped.json()["allowed_actions"] == ["save", "apply", "close"]

    reconsidered = decide(persona, skipped.json(), "save")
    assert reconsidered.json()["status"] == "saved"

    closed = decide(persona, reconsidered.json(), "close")
    assert closed.json()["status"] == "closed"
    assert closed.json()["allowed_actions"] == ["apply"]

    recorded = decisions(owner_session, opportunity["id"])
    assert [(item.payload["decision"], item.payload["to_status"]) for item in recorded] == [
        ("save", "saved"),
        ("skip", "skipped"),
        ("save", "saved"),
        ("close", "closed"),
    ]
    assert recorded[0].payload["reason"] == "looks promising"
    assert recorded[1].payload["reason"] == "too far"
    assert recorded[2].payload["reason"] is None
    assert {item.actor for item in recorded} == {"user"}
    assert {item.payload["schema_version"] for item in recorded} == {1}
    assert (
        scalar(
            owner_session,
            "SELECT content_updated_at FROM opportunities WHERE id = :id",
            id=opportunity["id"],
        )
        == content_updated_at
    )


@pytest.mark.parametrize(
    ("setup", "action"),
    [
        (["save"], "save"),
        (["skip"], "skip"),
        (["close"], "save"),
        (["close"], "skip"),
        (["close"], "close"),
        (["save", "skip"], "skip"),
    ],
)
def test_invalid_decisions_are_typed_409s_and_change_nothing(
    persona: Persona, owner_session: Session, setup: list[str], action: str
) -> None:
    opportunity = new_opportunity(persona, f"invalid {setup} {action}")
    for step in setup:
        opportunity = decide(persona, opportunity, step).json()
    before = len(decisions(owner_session, opportunity["id"]))

    response = decide(persona, opportunity, action)

    assert response.status_code == 409
    assert error_code(response) == "invalid_transition"
    assert (
        get_opportunity(persona, opportunity["id"])["state_version"]
        == (opportunity["state_version"])
    )
    assert len(decisions(owner_session, opportunity["id"])) == before


def test_an_applied_opportunity_refuses_every_decision(persona: Persona) -> None:
    opportunity, _ = applied(persona, "applied refuses")

    assert opportunity["status"] == "applied"
    assert opportunity["allowed_actions"] == []
    for action in ("save", "skip", "close", "apply"):
        response = decide(persona, opportunity, action)
        assert (response.status_code, error_code(response)) == (409, "invalid_transition")


def test_a_stale_version_is_a_conflict_before_anything_else(persona: Persona) -> None:
    opportunity = new_opportunity(persona, "stale")
    assert decide(persona, opportunity, "save").status_code == 200

    stale = decide(persona, opportunity, "skip")

    assert (stale.status_code, error_code(stale)) == (409, "conflict")


def test_decision_bodies_are_validated(persona: Persona) -> None:
    opportunity = new_opportunity(persona, "validation")

    assert decide(persona, opportunity, "save", reason="x" * 501).status_code == 422
    assert decide(persona, opportunity, "save", surprise=True).status_code == 422
    assert (
        persona.request(
            "POST", f"{OPPORTUNITIES}/{opportunity['id']}/save", json={"expected_state_version": 0}
        ).status_code
        == 422
    )
    assert get_opportunity(persona, opportunity["id"])["status"] == "new"


@pytest.mark.parametrize("path", ["save", "skip", "close"])
def test_decisions_on_unknown_opportunities_are_404(persona: Persona, path: str) -> None:
    response = persona.request(
        "POST", f"{OPPORTUNITIES}/{uuid.uuid4()}/{path}", json={"expected_state_version": 1}
    )

    assert (response.status_code, error_code(response)) == (404, "not_found")


def lane_and_resume(persona: Persona, name: str = "Platform") -> tuple[str, str]:
    lane = create_lane(persona, name)
    resume = upload(persona, synthetic_pdf(f"state-{name}"), lane_id=lane["id"], label=name).json()
    return lane["id"], resume["id"]


def test_apply_creates_the_application_and_both_events_atomically(
    persona: Persona, owner_session: Session
) -> None:
    lane_id, resume_id = lane_and_resume(persona)
    opportunity = new_opportunity(persona, "apply atomic")
    applied_at = when(days=-2)

    response = apply_to(
        persona,
        opportunity,
        resume_id=resume_id,
        lane_id=lane_id,
        channel="referral",
        applied_at=applied_at,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["opportunity"]["status"] == "applied"
    assert body["opportunity"]["state_version"] == opportunity["state_version"] + 1
    application = body["application"]
    assert application["stage"] == "applied"
    assert application["is_terminal"] is False
    assert application["state_version"] == 1
    assert application["channel"] == "referral"
    assert application["resume_id"] == resume_id
    assert application["lane_id"] == lane_id
    assert application["opportunity_title"] == opportunity["title"]
    assert datetime.fromisoformat(application["applied_at"]) == datetime.fromisoformat(applied_at)
    assert application["recordable_event_types"]
    assert "APPLICATION_SUBMITTED" not in application["recordable_event_types"]

    submitted = rows(
        owner_session,
        "SELECT occurred_at, actor, payload, correlation_id, source_ref_id FROM domain_events "
        "WHERE aggregate_type = 'application' AND aggregate_id = :id",
        id=application["id"],
    )
    assert len(submitted) == 1
    assert submitted[0].actor == "user"
    assert submitted[0].occurred_at == datetime.fromisoformat(applied_at)
    assert submitted[0].source_ref_id is None
    assert submitted[0].payload["channel"] == "referral"
    decided = decisions(owner_session, opportunity["id"])
    assert len(decided) == 1
    assert decided[0].payload["decision"] == "apply"
    assert decided[0].correlation_id is not None
    assert decided[0].correlation_id == submitted[0].correlation_id
    assert decided[0].occurred_at == submitted[0].occurred_at


def test_apply_defaults_to_now_other_channel_and_no_resume(
    persona: Persona, owner_session: Session
) -> None:
    opportunity = new_opportunity(persona, "apply defaults")

    response = apply_to(persona, opportunity)

    application = response.json()["application"]
    assert application["channel"] == "other"
    assert application["resume_id"] is None
    assert application["lane_id"] is None
    assert abs(datetime.fromisoformat(application["applied_at"]) - datetime.now(UTC)) < timedelta(
        minutes=1
    )
    assert scalar(owner_session, "SELECT count(*) FROM applications") == 1


@pytest.mark.parametrize("before", [["skip"], ["close"], ["save"]])
def test_apply_is_allowed_from_every_pre_applied_state(persona: Persona, before: list[str]) -> None:
    opportunity = new_opportunity(persona, f"apply from {before}")
    for step in before:
        opportunity = decide(persona, opportunity, step).json()

    response = apply_to(persona, opportunity)

    assert response.status_code == 200
    assert response.json()["opportunity"]["status"] == "applied"


def test_apply_refuses_foreign_archived_and_future_inputs_without_side_effects(
    persona: Persona, other: Persona, owner_session: Session
) -> None:
    lane_id, resume_id = lane_and_resume(persona)
    foreign_lane, foreign_resume = lane_and_resume(other, "Other lane")
    archived_lane, archived_resume = lane_and_resume(persona, "Archived lane")
    persona.request("POST", f"/api/v1/resumes/{archived_resume}/archive")
    persona.request("POST", f"/api/v1/lanes/{archived_lane}/archive")
    opportunity = new_opportunity(persona, "apply refusals")

    cases = [
        ({"resume_id": foreign_resume}, 404, "not_found"),
        ({"lane_id": foreign_lane}, 404, "not_found"),
        ({"resume_id": str(uuid.uuid4())}, 404, "not_found"),
        ({"resume_id": archived_resume}, 422, "resume_archived"),
        ({"lane_id": archived_lane}, 422, "lane_archived"),
        ({"applied_at": when(10)}, 422, "occurred_at_in_future"),
        ({"channel": "carrier_pigeon"}, 422, "validation_error"),
        ({"applied_at": "2026-01-01T00:00:00"}, 422, "validation_error"),
    ]
    for extra, status, code in cases:
        response = apply_to(
            persona, opportunity, **{"resume_id": resume_id, "lane_id": lane_id, **extra}
        )
        assert response.status_code == status, (extra, response.text)
        if status != 422 or code != "validation_error":
            assert error_code(response) == code, extra

    assert scalar(owner_session, "SELECT count(*) FROM applications") == 0
    assert decisions(owner_session, opportunity["id"]) == []
    assert (
        get_opportunity(persona, opportunity["id"])["state_version"]
        == (opportunity["state_version"])
    )


def test_applied_at_a_few_minutes_ahead_is_tolerated(persona: Persona) -> None:
    opportunity = new_opportunity(persona, "apply tolerance")

    assert apply_to(persona, opportunity, applied_at=when(4)).status_code == 200


def test_two_concurrent_applies_yield_one_application_and_one_conflict(
    persona: Persona, owner_session: Session
) -> None:
    opportunity = new_opportunity(persona, "apply race")
    barrier = threading.Barrier(2)
    statuses: list[int] = []
    codes: list[str] = []
    lock = threading.Lock()

    def attempt() -> None:
        barrier.wait()
        response = apply_to(persona, opportunity)
        with lock:
            statuses.append(response.status_code)
            if response.status_code != 200:
                codes.append(error_code(response))

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(statuses) == [200, 409]
    assert codes == ["conflict"]
    assert scalar(owner_session, "SELECT count(*) FROM applications") == 1
    assert len(decisions(owner_session, opportunity["id"])) == 1
    assert (
        scalar(
            owner_session,
            "SELECT count(*) FROM domain_events WHERE event_type = 'APPLICATION_SUBMITTED'",
        )
        == 1
    )


def test_concurrent_event_recordings_on_one_version_yield_one_conflict(
    persona: Persona, owner_session: Session
) -> None:
    _, application = applied(persona, "event race")
    barrier = threading.Barrier(2)
    statuses: list[int] = []
    lock = threading.Lock()

    def attempt(event_type: str) -> None:
        barrier.wait()
        response = record(persona, application, event_type)
        with lock:
            statuses.append(response.status_code)

    threads = [
        threading.Thread(target=attempt, args=(name,))
        for name in ("ASSESSMENT_RECEIVED", "INTERVIEW_REQUESTED")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(statuses) == [200, 409]
    stored, projected = stored_state(owner_session, application["id"])
    assert stored == projected
    assert current(persona, application)["state_version"] == application["state_version"] + 1


def test_second_non_terminal_application_for_an_opportunity_is_rejected_by_the_index(
    persona: Persona, owner_session: Session
) -> None:
    opportunity, application = applied(persona, "partial unique")

    with pytest.raises(Exception, match="uq_applications_open_per_opportunity"):
        owner_session.execute(
            text(
                "INSERT INTO applications (id, user_id, opportunity_id, applied_at) "
                "SELECT :id, user_id, opportunity_id, now() FROM applications WHERE id = :app"
            ),
            {"id": uuid.uuid4(), "app": application["id"]},
        )
    owner_session.rollback()
    assert opportunity["status"] == "applied"


def test_recording_the_full_story_keeps_stored_stage_equal_to_the_projection(
    persona: Persona, owner_session: Session
) -> None:
    opportunity, application = applied(persona, "full story", applied_at=when(days=-3))

    def step(response: Any, stage: str, terminal: bool) -> dict[str, Any]:
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        stored, projected = stored_state(owner_session, application["id"])
        assert (body["stage"], body["is_terminal"]) == (stage, terminal)
        assert stored == projected
        return body

    state = step(
        record(persona, application, "ASSESSMENT_RECEIVED", when(-30)), "assessment", False
    )
    state = step(record(persona, state, "INTERVIEW_SCHEDULED", when(-20)), "interviewing", False)
    state = step(
        record(persona, state, "INTERVIEW_REQUESTED", when(-25), note="backdated"),
        "interviewing",
        False,
    )
    state = step(record(persona, state, "REJECTED", when(-10)), "rejected", True)
    rejected_id = entry_for(timeline(persona, opportunity["id"]), "REJECTED")["id"]
    state = step(
        void(persona, state, rejected_id, reason="entered by mistake"), "interviewing", False
    )
    state = step(record(persona, state, "WITHDRAWN", when(-5)), "withdrawn", True)
    state = step(reopen(persona, state, note="changed my mind"), "interviewing", False)

    entries = timeline(persona, opportunity["id"])
    ordered = [entry["event_type"] for entry in entries]
    assert ordered.index("ASSESSMENT_RECEIVED") < ordered.index("INTERVIEW_REQUESTED")
    assert ordered.index("INTERVIEW_REQUESTED") < ordered.index("INTERVIEW_SCHEDULED")
    assert ordered.index("INTERVIEW_SCHEDULED") < ordered.index("REJECTED")
    assert ordered.index("REJECTED") < ordered.index("WITHDRAWN")
    keys = [(entry["occurred_at"], entry["recorded_at"], entry["id"]) for entry in entries]
    assert keys == sorted(keys)
    rejected = entry_for(entries, "REJECTED")
    assert rejected["voided"] is True
    assert rejected["voidable"] is False
    voiding = entry_for(entries, "EVENT_VOIDED")
    assert voiding["voids_event_id"] == rejected["id"]
    assert voiding["note"] == "entered by mistake"
    assert voiding["voidable"] is False
    assert entry_for(entries, "INTERVIEW_REQUESTED")["note"] == "backdated"
    assert entry_for(entries, "APPLICATION_REOPENED")["note"] == "changed my mind"
    assert entry_for(entries, "WITHDRAWN")["voidable"] is True
    assert entry_for(entries, "APPLICATION_SUBMITTED")["voidable"] is False
    assert entry_for(entries, "OPPORTUNITY_DECIDED")["voidable"] is False
    assert (state["stage"], state["is_terminal"]) == ("interviewing", False)


def test_backdating_and_future_limits_on_recorded_events(persona: Persona) -> None:
    _, application = applied(persona, "occurred limits")

    assert record(persona, application, "NOTE_ADDED", when(days=-300)).status_code == 200
    future = record(persona, current(persona, application), "NOTE_ADDED", when(6))
    assert (future.status_code, error_code(future)) == (422, "occurred_at_in_future")
    near = record(persona, current(persona, application), "NOTE_ADDED", when(4))
    assert near.status_code == 200
    naive = record(persona, current(persona, application), "NOTE_ADDED", "2026-01-01T00:00:00")
    assert naive.status_code == 422


@pytest.mark.parametrize(
    "event_type", ["APPLICATION_SUBMITTED", "APPLICATION_REOPENED", "EVENT_VOIDED"]
)
def test_reserved_event_types_cannot_be_recorded_directly(
    persona: Persona, owner_session: Session, event_type: str
) -> None:
    _, application = applied(persona, f"reserved {event_type}")

    response = record(persona, application, event_type)

    assert (response.status_code, error_code(response)) == (422, "event_type_not_allowed")
    assert current(persona, application)["state_version"] == application["state_version"]
    assert event_type not in application["recordable_event_types"]


def test_unknown_event_types_and_oversized_notes_are_validation_errors(persona: Persona) -> None:
    _, application = applied(persona, "bad bodies")

    assert record(persona, application, "TELEPATHY").status_code == 422
    assert record(persona, application, "NOTE_ADDED", note="n" * 1001).status_code == 422
    assert record(persona, application, "NOTE_ADDED", note="n" * 1000).status_code == 200


def test_a_second_terminal_event_while_terminal_is_refused(persona: Persona) -> None:
    _, application = applied(persona, "double terminal")
    state = record(persona, application, "REJECTED", when(-1)).json()
    assert state["is_terminal"] is True
    assert "REJECTED" not in state["recordable_event_types"]
    assert "NOTE_ADDED" in state["recordable_event_types"]

    again = record(persona, state, "WITHDRAWN")

    assert (again.status_code, error_code(again)) == (409, "invalid_transition")
    noted = record(persona, state, "NOTE_ADDED", note="still recordable")
    assert noted.status_code == 200
    assert noted.json()["stage"] == "rejected"


def test_void_refusals(persona: Persona, owner_session: Session) -> None:
    opportunity, application = applied(persona, "void refusals")
    state = record(persona, application, "NOTE_ADDED", when(-3)).json()
    state = record(persona, state, "OFFER_RECEIVED", when(-2)).json()
    entries = timeline(persona, opportunity["id"])
    submitted = entry_for(entries, "APPLICATION_SUBMITTED")
    decided = entry_for(entries, "OPPORTUNITY_DECIDED")
    note = entry_for(entries, "NOTE_ADDED")

    refusals = [
        (submitted["id"], 409, "cannot_void"),
        (decided["id"], 409, "cannot_void"),
    ]
    for event_id, status, code in refusals:
        response = void(persona, state, event_id)
        assert (response.status_code, error_code(response)) == (status, code)
    assert void(persona, state, str(uuid.uuid4())).status_code == 404

    voided = void(persona, state, note["id"])
    assert voided.status_code == 200
    state = voided.json()
    twice = void(persona, state, note["id"])
    assert (twice.status_code, error_code(twice)) == (409, "already_voided")
    voiding_id = entry_for(timeline(persona, opportunity["id"]), "EVENT_VOIDED")["id"]
    void_void = void(persona, state, voiding_id)
    assert (void_void.status_code, error_code(void_void)) == (409, "cannot_void")
    assert (
        stored_state(owner_session, application["id"])[0]
        == stored_state(owner_session, application["id"])[1]
    )


def test_voiding_another_applications_event_is_refused(persona: Persona) -> None:
    first_opportunity, first = applied(persona, "void cross one")
    second_opportunity, second = applied(persona, "void cross two")
    first = record(persona, first, "NOTE_ADDED", when(-1)).json()
    foreign_event = entry_for(timeline(persona, first_opportunity["id"]), "NOTE_ADDED")["id"]

    response = void(persona, second, foreign_event)

    assert (response.status_code, error_code(response)) == (409, "cannot_void")
    assert second_opportunity["status"] == "applied"


def test_reopen_needs_a_terminal_application_and_a_fresh_version(persona: Persona) -> None:
    _, application = applied(persona, "reopen rules")

    early = reopen(persona, application)
    assert (early.status_code, error_code(early)) == (409, "not_terminal")
    terminal = record(persona, application, "OFFER_DECLINED", when(-1)).json()
    stale = reopen(persona, application)
    assert (stale.status_code, error_code(stale)) == (409, "conflict")
    reopened = reopen(persona, terminal)
    assert reopened.status_code == 200
    assert reopened.json()["stage"] == "applied"
    assert reopened.json()["is_terminal"] is False


def test_a_terminal_event_dated_before_the_reopen_is_refused(persona: Persona) -> None:
    _, application = applied(persona, "terminal before reopen")
    state = record(persona, application, "REJECTED", when(-30)).json()
    state = reopen(persona, state).json()

    refused = record(persona, state, "WITHDRAWN", when(-20))

    assert (refused.status_code, error_code(refused)) == (409, "terminal_before_reopen")
    accepted = record(persona, state, "WITHDRAWN", when(1))
    assert accepted.status_code == 200
    assert accepted.json()["stage"] == "withdrawn"


def test_reopening_after_a_future_dated_terminal_still_clears_it(persona: Persona) -> None:
    _, application = applied(persona, "future terminal then reopen")
    state = record(persona, application, "REJECTED", when(4)).json()

    reopened = reopen(persona, state)

    assert reopened.json()["is_terminal"] is False


def test_application_commands_on_stale_versions_are_conflicts(persona: Persona) -> None:
    _, application = applied(persona, "stale application")
    assert record(persona, application, "NOTE_ADDED").status_code == 200

    response = record(persona, application, "ASSESSMENT_RECEIVED")

    assert (response.status_code, error_code(response)) == (409, "conflict")


def test_applications_list_filters_and_orders_newest_first(persona: Persona) -> None:
    _, older = applied(persona, "list older", applied_at=when(days=-5))
    _, newer = applied(persona, "list newer", applied_at=when(days=-1))
    record(persona, older, "REJECTED", when(-100))

    everything = persona.request("GET", APPLICATIONS).json()
    assert [item["id"] for item in everything] == [newer["id"], older["id"]]
    assert everything[0]["opportunity_title"] is None
    assert everything[0]["company_name"] is None
    open_only = persona.request("GET", APPLICATIONS, params={"is_terminal": "false"}).json()
    assert [item["id"] for item in open_only] == [newer["id"]]
    rejected = persona.request("GET", APPLICATIONS, params={"stage": "rejected"}).json()
    assert [item["id"] for item in rejected] == [older["id"]]
    by_opportunity = persona.request(
        "GET", APPLICATIONS, params={"opportunity_id": newer["opportunity_id"]}
    ).json()
    assert [item["id"] for item in by_opportunity] == [newer["id"]]
    assert persona.request("GET", APPLICATIONS, params={"stage": "nonsense"}).status_code == 422


def test_timeline_of_an_undecided_opportunity_lists_only_its_own_events(
    persona: Persona,
) -> None:
    opportunity = new_opportunity(persona, "timeline bare")
    decide(persona, opportunity, "save", reason="keep an eye on it")

    entries = timeline(persona, opportunity["id"])

    assert [entry["event_type"] for entry in entries] == [
        "OPPORTUNITY_INGESTED",
        "OPPORTUNITY_DECIDED",
    ]
    assert {entry["aggregate_type"] for entry in entries} == {"opportunity"}
    assert entries[1]["note"] == "keep an eye on it"
    assert entries[0]["note"] is None
    assert not any(entry["voidable"] or entry["voided"] for entry in entries)


def test_notes_are_stored_but_never_logged(
    persona: Persona, owner_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    secret_note = "synthetic-note-never-log-3f9a"
    secret_reason = "synthetic-reason-never-log-77c1"
    opportunity = new_opportunity(persona, "log hygiene")
    with caplog.at_level(logging.DEBUG):
        decide(persona, opportunity, "save", reason=secret_reason)
        applied_body = apply_to(persona, get_opportunity(persona, opportunity["id"])).json()
        state = record(persona, applied_body["application"], "NOTE_ADDED", note=secret_note).json()
        void(persona, state, entry_for(timeline(persona, opportunity["id"]), "NOTE_ADDED")["id"])

    assert secret_note not in caplog.text
    assert secret_reason not in caplog.text
    stored = scalar(
        owner_session,
        "SELECT count(*) FROM domain_events WHERE payload::text LIKE :needle",
        needle=f"%{secret_note}%",
    )
    assert stored == 1


def test_stored_stage_always_equals_the_projection_after_random_command_sequences(
    persona: Persona, owner_session: Session
) -> None:
    types = [
        event.value
        for event in ApplicationEventType
        if event
        not in {
            ApplicationEventType.APPLICATION_SUBMITTED,
            ApplicationEventType.APPLICATION_REOPENED,
            ApplicationEventType.EVENT_VOIDED,
        }
    ]
    accepted_codes = {
        "invalid_transition",
        "terminal_before_reopen",
        "cannot_void",
        "already_voided",
        "not_terminal",
    }
    for seed in range(4):
        generator = random.Random(seed)
        _, application = applied(persona, f"random {seed}", applied_at=when(days=-10))
        state = application
        executed = 0
        for _ in range(40):
            choice = generator.random()
            if choice < 0.65:
                response = record(
                    persona,
                    state,
                    generator.choice(types),
                    when(generator.uniform(-6000, 3)),
                )
            elif choice < 0.85:
                events = timeline(persona, state["opportunity_id"])
                targets = [entry for entry in events if entry["voidable"]]
                if not targets:
                    continue
                response = void(persona, state, generator.choice(targets)["id"])
            else:
                response = reopen(persona, state)
            if response.status_code == 200:
                state = response.json()
                executed += 1
            else:
                assert response.status_code == 409, response.text
                assert error_code(response) in accepted_codes
            stored, projected = stored_state(owner_session, application["id"])
            assert stored == projected
            assert (state["stage"], state["is_terminal"]) == (
                stored.stage.value,
                stored.is_terminal,
            )
        assert executed > 5
    assert (
        scalar(
            owner_session,
            "SELECT count(*) FROM applications a WHERE a.is_terminal <> "
            "(a.stage IN ('rejected', 'withdrawn', 'accepted', 'declined', 'no_response'))",
        )
        == 0
    )
    row(owner_session, "SELECT 1")
