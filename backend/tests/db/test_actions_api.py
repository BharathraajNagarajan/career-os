import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.actions.jobs import WAKE_ACTION_JOB, WakeActionPayload, wake_unique_key
from app.actions.service import ActionService
from app.actions.wake import make_wake_action_handler
from app.config import Settings
from app.db.models import Actor
from app.jobs.queue import enqueue
from app.jobs.registry import JobRegistry
from app.jobs.runner import JobRunner
from app.state_machines.recruiting_action import RecruitingActionCommand
from tests.auth.fake_idp import FakeIdentityProvider
from tests.db.application_helpers import applied, new_opportunity, timeline
from tests.db.auth_helpers import Persona, make_persona
from tests.db.contact_helpers import (
    ACTIONS,
    action_command,
    body_of,
    create_action,
    create_contact,
    create_interaction,
    error_code,
    future,
)
from tests.db.opportunity_helpers import row, rows, scalar

pytestmark = pytest.mark.db


@pytest.fixture
def persona(app: FastAPI, idp: FakeIdentityProvider) -> Persona:
    return make_persona(app, idp, "a")


@pytest.fixture
def other(app: FastAPI, idp: FakeIdentityProvider) -> Persona:
    return make_persona(app, idp, "b")


def made(persona: Persona, kind: str = "custom", **extra: Any) -> dict[str, Any]:
    return body_of(create_action(persona, kind, **extra), 201)


def fetched(persona: Persona, action: dict[str, Any]) -> dict[str, Any]:
    return body_of(persona.request("GET", f"{ACTIONS}/{action['id']}"))


def action_events(owner: Session, action_id: str) -> list[Any]:
    return rows(
        owner,
        "SELECT event_type, actor, payload FROM domain_events WHERE aggregate_type = "
        "'recruiting_action' AND aggregate_id = :id ORDER BY recorded_at, id",
        id=action_id,
    )


def wake_jobs(owner: Session) -> list[Any]:
    return rows(
        owner,
        "SELECT status, payload, unique_key, run_after FROM jobs WHERE kind = 'wake_action' "
        "ORDER BY created_at, id",
    )


def make_due(owner: Session) -> None:
    owner.rollback()
    owner.execute(text("UPDATE jobs SET run_after = now() - interval '1 second'"))
    owner.commit()


def run_wake_jobs(app_sessions: sessionmaker[Session], settings: Settings) -> int:
    registry = JobRegistry()
    registry.register(WAKE_ACTION_JOB, WakeActionPayload, make_wake_action_handler())
    runner = JobRunner(app_sessions, registry, settings, worker_id="wake-test")
    processed = 0
    while runner.run_once():
        processed += 1
    return processed


def test_a_new_action_is_open_with_user_origin_and_an_event(
    persona: Persona, owner_session: Session
) -> None:
    action = made(persona, title="  Reply   to Alex Example ", due_at=future(days=2))

    assert action["status"] == "open"
    assert action["origin"] == "user"
    assert action["title"] == "Reply to Alex Example"
    assert action["state_version"] == 1
    assert action["sequence_no"] == 1
    assert action["allowed_actions"] == ["snooze", "complete", "dismiss"]
    events = action_events(owner_session, action["id"])
    assert [(event.event_type, event.actor) for event in events] == [
        ("RECRUITING_ACTION_CREATED", "user")
    ]
    assert "title" not in events[0].payload


@pytest.mark.parametrize("kind", ["attend_interview", "complete_assessment"])
def test_scheduled_kinds_require_a_due_time(persona: Persona, kind: str) -> None:
    missing = create_action(persona, kind)
    assert (missing.status_code, error_code(missing)) == (422, "due_at_required")

    created = made(persona, kind, due_at=future(days=1))
    assert created["kind"] == kind
    assert created["due_at"] is not None


@pytest.mark.parametrize("kind", ["follow_up", "reply", "schedule_interview", "custom"])
def test_other_kinds_do_not_need_a_due_time(persona: Persona, kind: str) -> None:
    assert made(persona, kind)["due_at"] is None


def test_review_is_gone_and_outreach_is_not_creatable_here(persona: Persona) -> None:
    assert create_action(persona, "review").status_code == 422
    outreach = create_action(persona, "outreach")
    assert (outreach.status_code, error_code(outreach)) == (422, "kind_not_creatable")


@pytest.mark.parametrize(
    "extra",
    [{"title": ""}, {"title": "x" * 201}, {"due_at": "2026-01-01T10:00:00"}, {"unknown": 1}],
)
def test_invalid_actions_are_rejected(persona: Persona, extra: dict[str, Any]) -> None:
    payload = {"kind": "custom", "title": "A title", **extra}

    assert persona.request("POST", ACTIONS, json=payload).status_code == 422


def test_follow_ups_are_numbered_per_application(persona: Persona) -> None:
    _, application = applied(persona, "follow up numbering")
    _, other_application = applied(persona, "follow up numbering two")

    numbers = [
        made(persona, "follow_up", application_id=application["id"])["sequence_no"]
        for _ in range(3)
    ]
    separate = made(persona, "follow_up", application_id=other_application["id"])

    assert numbers == [1, 2, 3]
    assert separate["sequence_no"] == 1
    assert made(persona, "reply", application_id=application["id"])["sequence_no"] == 1


def test_references_are_resolved_as_the_callers(persona: Persona, other: Persona) -> None:
    opportunity, application = applied(persona, "action refs")
    unrelated = new_opportunity(persona, "action refs unrelated")
    contact = create_contact(persona)
    foreign_contact = create_contact(other, "Sam Example")
    foreign_opportunity = new_opportunity(other, "foreign action ref")

    created = made(persona, application_id=application["id"], contact_id=contact["id"])
    assert created["opportunity_id"] == opportunity["id"]
    for extra in (
        {"contact_id": foreign_contact["id"]},
        {"opportunity_id": foreign_opportunity["id"]},
        {"application_id": str(uuid.uuid4())},
        {"interaction_id": str(uuid.uuid4())},
    ):
        assert create_action(persona, **extra).status_code == 404
    mismatch = create_action(
        persona, application_id=application["id"], opportunity_id=unrelated["id"]
    )
    assert (mismatch.status_code, error_code(mismatch)) == (422, "application_opportunity_mismatch")


def test_an_action_can_reference_an_interaction(persona: Persona) -> None:
    contact = create_contact(persona)
    interaction = body_of(create_interaction(persona, contact["id"]), 201)

    action = made(persona, "follow_up", contact_id=contact["id"], interaction_id=interaction["id"])

    assert action["interaction_id"] == interaction["id"]


def test_complete_and_dismiss_are_terminal(persona: Persona, owner_session: Session) -> None:
    done = made(persona)
    dismissed = made(persona)

    completed = body_of(action_command(persona, done, "complete"))
    gone = body_of(action_command(persona, dismissed, "dismiss"))

    assert (completed["status"], completed["allowed_actions"]) == ("done", [])
    assert (gone["status"], gone["allowed_actions"]) == ("dismissed", [])
    assert completed["state_version"] == 2
    for command in ("complete", "dismiss", "snooze"):
        extra = {"until": future(60)} if command == "snooze" else {}
        response = action_command(persona, completed, command, **extra)
        assert response.status_code == 409
    again = action_command(persona, fetched(persona, done), "complete")
    assert (again.status_code, error_code(again)) == (409, "invalid_transition")
    assert [event.event_type for event in action_events(owner_session, done["id"])] == [
        "RECRUITING_ACTION_CREATED",
        "RECRUITING_ACTION_COMPLETED",
    ]


def test_a_stale_version_is_a_conflict_and_changes_nothing(persona: Persona) -> None:
    action = made(persona)
    body_of(action_command(persona, action, "snooze", until=future(60)))

    stale = action_command(persona, action, "dismiss")

    assert (stale.status_code, error_code(stale)) == (409, "conflict")
    assert fetched(persona, action)["status"] == "snoozed"


def test_snooze_must_end_in_the_future_and_cannot_repeat(persona: Persona) -> None:
    action = made(persona)

    past = action_command(persona, action, "snooze", until=future(-1))
    assert (past.status_code, error_code(past)) == (422, "snooze_not_in_future")
    assert fetched(persona, action)["status"] == "open"

    snoozed = body_of(action_command(persona, action, "snooze", until=future(60)))
    assert snoozed["status"] == "snoozed"
    assert snoozed["allowed_actions"] == ["complete", "dismiss"]
    assert action_command(persona, snoozed, "snooze", until=future(120)).status_code == 409


def test_snoozing_queues_one_wake_job_with_the_run_time_and_version(
    persona: Persona, owner_session: Session
) -> None:
    action = made(persona)
    until = datetime.now(UTC) + timedelta(hours=3)

    snoozed = body_of(action_command(persona, action, "snooze", until=until.isoformat()))

    jobs = wake_jobs(owner_session)
    assert len(jobs) == 1
    assert jobs[0].unique_key == wake_unique_key(uuid.UUID(action["id"]), snoozed["state_version"])
    assert jobs[0].payload == {"action_id": action["id"], "state_version": snoozed["state_version"]}
    assert abs((jobs[0].run_after - until).total_seconds()) < 1
    assert snoozed["snoozed_until"] is not None


def test_the_worker_wakes_a_snoozed_action_exactly_once(
    persona: Persona,
    owner_session: Session,
    app_sessions: sessionmaker[Session],
    db_settings: Settings,
) -> None:
    action = made(persona)
    snoozed = body_of(action_command(persona, action, "snooze", until=future(60)))
    assert run_wake_jobs(app_sessions, db_settings) == 0
    assert fetched(persona, action)["status"] == "snoozed"

    make_due(owner_session)
    assert run_wake_jobs(app_sessions, db_settings) == 1
    assert run_wake_jobs(app_sessions, db_settings) == 0

    woken = fetched(persona, action)
    assert woken["status"] == "open"
    assert woken["snoozed_until"] is None
    assert woken["state_version"] == snoozed["state_version"] + 1
    assert woken["allowed_actions"] == ["snooze", "complete", "dismiss"]
    events = action_events(owner_session, action["id"])
    assert [(event.event_type, event.actor) for event in events][-1] == (
        "RECRUITING_ACTION_WOKEN",
        "system",
    )
    assert [event.event_type for event in events].count("RECRUITING_ACTION_WOKEN") == 1
    assert wake_jobs(owner_session)[0].status == "succeeded"


def test_a_wake_job_for_a_stale_version_does_nothing(
    persona: Persona,
    owner_session: Session,
    app_sessions: sessionmaker[Session],
    db_settings: Settings,
) -> None:
    action = made(persona)
    first = body_of(action_command(persona, action, "snooze", until=future(60)))
    owner_session.execute(
        text(
            "UPDATE recruiting_actions SET status = 'open', snoozed_until = NULL, "
            "state_version = :version WHERE id = :id"
        ),
        {"version": first["state_version"] + 1, "id": action["id"]},
    )
    owner_session.commit()
    second = body_of(action_command(persona, fetched(persona, action), "snooze", until=future(120)))
    assert second["state_version"] == first["state_version"] + 2
    assert len(wake_jobs(owner_session)) == 2
    owner_session.rollback()
    owner_session.execute(
        text(
            "UPDATE jobs SET run_after = now() - interval '1 second' "
            "WHERE payload ->> 'state_version' = :v"
        ),
        {"v": str(first["state_version"])},
    )
    owner_session.commit()

    assert run_wake_jobs(app_sessions, db_settings) == 1

    still = fetched(persona, action)
    assert still["status"] == "snoozed"
    assert still["state_version"] == second["state_version"]
    assert [event.event_type for event in action_events(owner_session, action["id"])].count(
        "RECRUITING_ACTION_WOKEN"
    ) == 0

    make_due(owner_session)
    assert run_wake_jobs(app_sessions, db_settings) == 1
    assert fetched(persona, action)["status"] == "open"


@pytest.mark.parametrize("finish", ["complete", "dismiss"])
def test_a_wake_job_ignores_an_action_that_is_no_longer_snoozed(
    persona: Persona,
    owner_session: Session,
    app_sessions: sessionmaker[Session],
    db_settings: Settings,
    finish: str,
) -> None:
    action = made(persona)
    snoozed = body_of(action_command(persona, action, "snooze", until=future(60)))
    finished = body_of(action_command(persona, snoozed, finish))
    make_due(owner_session)

    assert run_wake_jobs(app_sessions, db_settings) == 1

    after = fetched(persona, action)
    assert after["status"] == finished["status"]
    assert after["state_version"] == finished["state_version"]
    assert "RECRUITING_ACTION_WOKEN" not in [
        event.event_type for event in action_events(owner_session, action["id"])
    ]


def test_a_second_wake_job_for_an_already_woken_action_does_nothing(
    persona: Persona,
    owner_session: Session,
    app_sessions: sessionmaker[Session],
    db_settings: Settings,
) -> None:
    action = made(persona)
    snoozed = body_of(action_command(persona, action, "snooze", until=future(60)))
    make_due(owner_session)
    run_wake_jobs(app_sessions, db_settings)
    woken = fetched(persona, action)
    with app_sessions() as session:
        enqueue(
            session,
            kind=WAKE_ACTION_JOB,
            payload=WakeActionPayload(
                action_id=uuid.UUID(action["id"]), state_version=snoozed["state_version"]
            ),
            user_id=uuid.UUID(str(scalar(owner_session, "SELECT user_id FROM recruiting_actions"))),
        )
        session.commit()

    assert run_wake_jobs(app_sessions, db_settings) == 1

    assert fetched(persona, action)["state_version"] == woken["state_version"]
    assert [event.event_type for event in action_events(owner_session, action["id"])].count(
        "RECRUITING_ACTION_WOKEN"
    ) == 1


def test_a_wake_job_for_a_missing_action_succeeds_quietly(
    persona: Persona,
    owner_session: Session,
    app_sessions: sessionmaker[Session],
    db_settings: Settings,
) -> None:
    made(persona)
    user_id = uuid.UUID(str(scalar(owner_session, "SELECT user_id FROM recruiting_actions")))
    with app_sessions() as session:
        enqueue(
            session,
            kind=WAKE_ACTION_JOB,
            payload=WakeActionPayload(action_id=uuid.uuid4(), state_version=1),
            user_id=user_id,
        )
        session.commit()

    assert run_wake_jobs(app_sessions, db_settings) == 1
    assert row(owner_session, "SELECT status FROM jobs").status == "succeeded"


def test_edits_change_title_and_due_time_without_a_new_version(
    persona: Persona, owner_session: Session
) -> None:
    action = made(persona, "attend_interview", due_at=future(days=1))
    new_due = future(days=2)

    edited = body_of(
        persona.request(
            "PATCH",
            f"{ACTIONS}/{action['id']}",
            json={
                "expected_state_version": action["state_version"],
                "title": "Interview with Alex Example",
                "due_at": new_due,
            },
        )
    )

    assert edited["title"] == "Interview with Alex Example"
    assert edited["state_version"] == action["state_version"]
    assert datetime.fromisoformat(edited["due_at"]) == datetime.fromisoformat(new_due)
    events = action_events(owner_session, action["id"])
    assert events[-1].event_type == "RECRUITING_ACTION_EDITED"
    assert events[-1].payload["fields"] == ["title", "due_at"]
    cleared = persona.request(
        "PATCH",
        f"{ACTIONS}/{action['id']}",
        json={"expected_state_version": edited["state_version"], "due_at": None},
    )
    assert (cleared.status_code, error_code(cleared)) == (422, "due_at_required")


def test_a_snoozed_action_can_be_edited_and_still_wakes(
    persona: Persona,
    owner_session: Session,
    app_sessions: sessionmaker[Session],
    db_settings: Settings,
) -> None:
    action = made(persona, "follow_up")
    snoozed = body_of(action_command(persona, action, "snooze", until=future(60)))

    body_of(
        persona.request(
            "PATCH",
            f"{ACTIONS}/{action['id']}",
            json={"expected_state_version": snoozed["state_version"], "due_at": future(days=3)},
        )
    )
    make_due(owner_session)
    run_wake_jobs(app_sessions, db_settings)

    assert fetched(persona, action)["status"] == "open"


def test_finished_actions_cannot_be_edited_and_stale_edits_conflict(persona: Persona) -> None:
    action = made(persona)
    done = body_of(action_command(persona, action, "complete"))

    refused = persona.request(
        "PATCH",
        f"{ACTIONS}/{action['id']}",
        json={"expected_state_version": done["state_version"], "title": "Too late"},
    )
    stale = persona.request(
        "PATCH",
        f"{ACTIONS}/{action['id']}",
        json={"expected_state_version": action["state_version"], "title": "Stale"},
    )

    assert (refused.status_code, error_code(refused)) == (409, "invalid_transition")
    assert (stale.status_code, error_code(stale)) == (409, "conflict")
    assert fetched(persona, action)["title"] == "Follow up with Alex Example"


def test_list_orders_by_due_time_with_nulls_last_and_filters(persona: Persona) -> None:
    contact = create_contact(persona)
    _, application = applied(persona, "action list")
    made(persona, "reply", title="Late", due_at=future(days=5))
    made(persona, "reply", title="Soon", due_at=future(days=1), contact_id=contact["id"])
    undated = made(persona, "custom", title="Undated", application_id=application["id"])
    finished = made(persona, "custom", title="Finished")
    body_of(action_command(persona, finished, "complete"))

    def titles(**params: Any) -> list[str]:
        response = persona.request("GET", ACTIONS, params=params)
        return [item["title"] for item in body_of_list(response)]

    assert titles(status="open") == ["Soon", "Late", "Undated"]
    assert titles(status=["done", "dismissed"]) == ["Finished"]
    assert titles(kind="reply") == ["Soon", "Late"]
    assert titles(contact_id=contact["id"]) == ["Soon"]
    assert titles(application_id=application["id"]) == ["Undated"]
    assert titles(opportunity_id=undated["opportunity_id"]) == ["Undated"]


def body_of_list(response: Any) -> list[dict[str, Any]]:
    assert response.status_code == 200, response.text
    body: list[dict[str, Any]] = response.json()
    return body


def test_supersede_and_restore_are_not_exposed(persona: Persona) -> None:
    action = made(persona)

    for command in ("supersede", "restore", "wake"):
        response = action_command(persona, action, command)
        assert response.status_code in {404, 405}


def test_the_system_can_supersede_and_restore_but_the_user_cannot(
    persona: Persona, owner_session: Session, app_sessions: sessionmaker[Session]
) -> None:
    action = made(persona)
    user_id = uuid.UUID(str(scalar(owner_session, "SELECT user_id FROM recruiting_actions")))

    with app_sessions() as session:
        service = ActionService(session)
        superseded = service.transition(
            user_id=user_id,
            action_id=uuid.UUID(action["id"]),
            command=RecruitingActionCommand.SUPERSEDE,
            expected_state_version=1,
            actor=Actor.SYSTEM,
        )
        superseded_status, superseded_version = superseded.status.value, superseded.state_version
        restored = service.transition(
            user_id=user_id,
            action_id=uuid.UUID(action["id"]),
            command=RecruitingActionCommand.RESTORE,
            expected_state_version=superseded_version,
            actor=Actor.SYSTEM,
        )
        assert (superseded_status, restored.status.value) == ("superseded", "open")

    events = action_events(owner_session, action["id"])
    assert [(event.event_type, event.actor) for event in events][1:] == [
        ("RECRUITING_ACTION_SUPERSEDED", "system"),
        ("RECRUITING_ACTION_RESTORED", "system"),
    ]


def test_action_events_appear_in_the_opportunity_timeline(persona: Persona) -> None:
    opportunity, application = applied(persona, "action timeline")
    made(persona, "attend_interview", title="Interview prep", due_at=future(days=1))
    linked = made(persona, "follow_up", title="Nudge recruiter", application_id=application["id"])
    direct = made(persona, "custom", title="Review posting", opportunity_id=opportunity["id"])
    made(persona, "custom", title="Unrelated")
    body_of(action_command(persona, linked, "complete"))
    body_of(action_command(persona, direct, "snooze", until=future(60)))

    entries = [
        (entry["event_type"], entry["note"])
        for entry in timeline(persona, opportunity["id"])
        if entry["aggregate_type"] == "recruiting_action"
    ]

    assert sorted(entries) == sorted(
        [
            ("RECRUITING_ACTION_CREATED", "Nudge recruiter"),
            ("RECRUITING_ACTION_COMPLETED", "Nudge recruiter"),
            ("RECRUITING_ACTION_CREATED", "Review posting"),
            ("RECRUITING_ACTION_SNOOZED", "Review posting"),
        ]
    )
