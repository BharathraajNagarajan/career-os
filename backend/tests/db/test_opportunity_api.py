import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from tests.auth.fake_idp import FakeIdentityProvider
from tests.db.auth_helpers import Persona, make_persona, new_client
from tests.db.opportunity_helpers import (
    SYNTHETIC_JD,
    extraction_json,
    get_opportunity,
    ingest,
    ingest_and_extract,
    ingest_ok,
    jd_variant,
    rows,
    scalar,
)

pytestmark = pytest.mark.db

OPPORTUNITIES = "/api/v1/opportunities"
COMPANIES = "/api/v1/companies"


@pytest.fixture
def persona(app: FastAPI, idp: FakeIdentityProvider) -> Persona:
    return make_persona(app, idp, "a")


@pytest.fixture
def other(app: FastAPI, idp: FakeIdentityProvider) -> Persona:
    return make_persona(app, idp, "b")


def moment(value: str) -> datetime:
    return datetime.fromisoformat(value)


def events(owner: Session, aggregate_id: str) -> list[Any]:
    return rows(
        owner,
        "SELECT event_type, actor, payload FROM domain_events WHERE aggregate_id = :id "
        "ORDER BY recorded_at, id",
        id=aggregate_id,
    )


def patch_body(opportunity: dict[str, Any], **fields: Any) -> dict[str, Any]:
    return {"expected_state_version": opportunity["state_version"], **fields}


def test_ingest_creates_the_artifact_opportunity_event_and_job_atomically(
    persona: Persona, owner_session: Session, app: FastAPI
) -> None:
    response = ingest(persona, f"  {SYNTHETIC_JD}  ", source_url="https://example.test/jobs/1")

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "new"
    assert body["priority"] == "normal"
    assert body["extraction_status"] == "pending"
    assert body["company"] is None
    assert body["title"] is None
    assert body["source_url"] == "https://example.test/jobs/1"
    assert body["state_version"] == 1
    stored = SYNTHETIC_JD.strip()
    artifact = rows(
        owner_session,
        "SELECT a.kind, a.sha256, a.mime_type, a.byte_size, a.extracted_text, "
        "a.extraction_status, a.storage_key FROM opportunities o "
        "JOIN artifacts a ON a.id = o.jd_artifact_id WHERE o.id = :id",
        id=body["id"],
    )[0]
    assert artifact.kind == "jd_snapshot"
    assert bytes(artifact.sha256) == hashlib.sha256(stored.encode()).digest()
    assert artifact.mime_type == "text/plain; charset=utf-8"
    assert artifact.byte_size == len(stored.encode())
    assert artifact.extracted_text == stored
    assert artifact.extraction_status == "succeeded"
    with app.state.storage.open(artifact.storage_key) as handle:
        assert handle.read() == stored.encode()
    job = rows(
        owner_session,
        "SELECT kind, user_id, payload, unique_key, status FROM jobs WHERE kind = 'extract_jd'",
    )
    assert len(job) == 1
    assert job[0].payload == {"opportunity_id": body["id"]}
    assert job[0].unique_key == f"extract_jd:{body['id']}"
    assert str(job[0].user_id) == str(persona.user_id)
    assert job[0].status == "queued"
    recorded = events(owner_session, body["id"])
    assert [(event.event_type, event.actor) for event in recorded] == [
        ("OPPORTUNITY_INGESTED", "user")
    ]
    assert set(recorded[0].payload) == {
        "schema_version",
        "opportunity_id",
        "artifact_id",
        "has_source_url",
    }
    assert scalar(
        owner_session,
        "SELECT content_updated_at = discovered_at FROM opportunities WHERE id = :id",
        id=body["id"],
    )


def test_an_identical_paste_is_rejected_with_the_existing_opportunity_id(
    persona: Persona, other: Persona, owner_session: Session
) -> None:
    first = ingest_ok(persona, SYNTHETIC_JD)

    again = ingest(persona, SYNTHETIC_JD.replace("\n", "\r\n") + "\r\n\r\n")
    foreign = ingest(other, SYNTHETIC_JD)

    assert again.status_code == 409
    assert again.json() == {"error": {"code": "duplicate_jd", "opportunity_id": first}}
    assert foreign.status_code == 202
    assert foreign.json()["id"] != first
    assert scalar(owner_session, "SELECT count(*) FROM artifacts") == 2
    assert scalar(owner_session, "SELECT count(*) FROM jobs WHERE kind = 'extract_jd'") == 2


def test_ingest_validates_length_and_source_url(persona: Persona, db_settings: Settings) -> None:
    short = ingest(persona, "x" * (db_settings.jd_min_chars - 1))
    padded = ingest(persona, "   " + "x" * 50 + "\n\n   " + " " * 500)
    long = ingest(persona, "y" * (db_settings.jd_max_chars + 1))
    exact_min = ingest(persona, "m" * db_settings.jd_min_chars)
    exact_max = ingest(persona, "z" * db_settings.jd_max_chars)

    assert short.status_code == 422
    assert short.json() == {"error": {"code": "jd_too_short"}}
    assert padded.json() == {"error": {"code": "jd_too_short"}}
    assert long.json() == {"error": {"code": "jd_too_long"}}
    assert exact_min.status_code == 202
    assert exact_max.status_code == 202
    for bad in (
        "javascript:alert(1)",
        "ftp://example.test/x",
        "example.test/jobs",
        "https://example.test/" + "a" * 2100,
    ):
        assert ingest(persona, jd_variant(bad[:10]), source_url=bad).status_code == 422
    assert ingest(persona, jd_variant("blank"), source_url="  ").status_code == 202


def test_ingest_requires_a_csrf_token(persona: Persona) -> None:
    response = persona.client.post(f"{OPPORTUNITIES}/ingest", json={"jd_text": SYNTHETIC_JD})

    assert response.status_code == 403


def test_a_failed_ingest_leaves_no_object_or_rows_behind(
    persona: Persona,
    owner_session: Session,
    app: FastAPI,
    db_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr("app.opportunities.service.enqueue", explode)

    with pytest.raises(RuntimeError):
        ingest(persona, SYNTHETIC_JD)

    stored = [path for path in Path(db_settings.artifact_storage_dir).rglob("*") if path.is_file()]
    assert stored == []
    assert scalar(owner_session, "SELECT count(*) FROM artifacts") == 0
    assert scalar(owner_session, "SELECT count(*) FROM opportunities") == 0
    assert scalar(owner_session, "SELECT count(*) FROM domain_events") == 0


def test_the_ingest_response_and_detail_never_fetch_or_render_the_url(
    persona: Persona,
) -> None:
    hostile = "https://example.test/<script>alert(1)</script>"
    opportunity_id = ingest_ok(persona, SYNTHETIC_JD, source_url=hostile)

    detail = get_opportunity(persona, opportunity_id)

    assert detail["source_url"] == hostile
    assert detail["jd_text"] == SYNTHETIC_JD.strip()


def test_list_filters_and_orders_newest_first(
    persona: Persona, app_sessions: sessionmaker[Session], db_settings: Settings
) -> None:
    first = ingest_and_extract(
        persona, app_sessions, db_settings, [extraction_json()], jd_variant("one")
    )
    second = ingest_ok(persona, jd_variant("two"))
    persona.request("PATCH", f"{OPPORTUNITIES}/{second}/priority", json={"priority": "high"})
    company_id = get_opportunity(persona, first)["company"]["id"]

    everything = persona.request("GET", OPPORTUNITIES).json()
    high = persona.request("GET", OPPORTUNITIES, params={"priority": "high"}).json()
    low = persona.request("GET", OPPORTUNITIES, params={"priority": "low"}).json()
    new = persona.request("GET", OPPORTUNITIES, params={"status": "new"}).json()
    applied = persona.request("GET", OPPORTUNITIES, params={"status": "applied"}).json()
    by_company = persona.request("GET", OPPORTUNITIES, params={"company_id": company_id}).json()

    assert [row["id"] for row in everything] == [second, first]
    assert [row["id"] for row in high] == [second]
    assert low == []
    assert len(new) == 2
    assert applied == []
    assert [row["id"] for row in by_company] == [first]
    assert by_company[0]["company"]["name"] == "Example Corp"
    assert persona.request("GET", OPPORTUNITIES, params={"status": "bogus"}).status_code == 422


def test_editing_content_bumps_content_updated_at_and_version_and_records_field_names(
    persona: Persona, owner_session: Session
) -> None:
    opportunity_id = ingest_ok(persona, SYNTHETIC_JD)
    before = get_opportunity(persona, opportunity_id)

    response = persona.request(
        "PATCH",
        f"{OPPORTUNITIES}/{opportunity_id}",
        json=patch_body(
            before,
            title="  Widget   Lead ",
            team="Platform",
            external_job_id="EX-7",
            location_text="Springfield",
            locations={"items": [{"city": "Springfield", "region": "IL", "country": "us"}]},
            workplace_type="remote",
            source_url="https://example.test/new",
        ),
    )

    assert response.status_code == 200, response.text
    after = response.json()
    assert after["title"] == "Widget Lead"
    assert after["team"] == "Platform"
    assert after["external_job_id"] == "EX-7"
    assert after["workplace_type"] == "remote"
    assert after["source_url"] == "https://example.test/new"
    assert after["locations"] == {
        "schema_version": 1,
        "items": [{"city": "Springfield", "region": "IL", "country": "US"}],
    }
    assert after["state_version"] == before["state_version"] + 1
    assert moment(after["content_updated_at"]) > moment(before["content_updated_at"])
    edited = events(owner_session, opportunity_id)[-1]
    assert edited.event_type == "OPPORTUNITY_CONTENT_EDITED"
    assert edited.payload["fields"] == sorted(
        [
            "external_job_id",
            "location_text",
            "locations",
            "source_url",
            "team",
            "title",
            "workplace_type",
        ]
    )
    assert "Widget" not in str(edited.payload)


def test_clearing_optional_fields_with_null(persona: Persona) -> None:
    opportunity_id = ingest_ok(persona, SYNTHETIC_JD, source_url="https://example.test/a")
    opportunity = get_opportunity(persona, opportunity_id)
    titled = persona.request(
        "PATCH", f"{OPPORTUNITIES}/{opportunity_id}", json=patch_body(opportunity, title="T")
    ).json()

    cleared = persona.request(
        "PATCH",
        f"{OPPORTUNITIES}/{opportunity_id}",
        json=patch_body(titled, title=None, source_url=None),
    ).json()

    assert cleared["title"] is None
    assert cleared["source_url"] is None


def test_a_stale_version_is_a_conflict_and_changes_nothing(persona: Persona) -> None:
    opportunity_id = ingest_ok(persona, SYNTHETIC_JD)
    opportunity = get_opportunity(persona, opportunity_id)
    persona.request(
        "PATCH", f"{OPPORTUNITIES}/{opportunity_id}", json=patch_body(opportunity, title="First")
    )

    stale = persona.request(
        "PATCH", f"{OPPORTUNITIES}/{opportunity_id}", json=patch_body(opportunity, title="Second")
    )

    assert stale.status_code == 409
    assert stale.json() == {"error": {"code": "conflict"}}
    assert get_opportunity(persona, opportunity_id)["title"] == "First"


def test_a_no_op_edit_changes_nothing(persona: Persona, owner_session: Session) -> None:
    opportunity_id = ingest_ok(persona, SYNTHETIC_JD)
    opportunity = get_opportunity(persona, opportunity_id)
    edited = persona.request(
        "PATCH", f"{OPPORTUNITIES}/{opportunity_id}", json=patch_body(opportunity, title="Same")
    ).json()
    event_count = len(events(owner_session, opportunity_id))

    again = persona.request(
        "PATCH",
        f"{OPPORTUNITIES}/{opportunity_id}",
        json=patch_body(edited, title="Same", workplace_type="unspecified"),
    )

    assert again.status_code == 200
    assert again.json()["state_version"] == edited["state_version"]
    assert again.json()["content_updated_at"] == edited["content_updated_at"]
    assert len(events(owner_session, opportunity_id)) == event_count


def test_job_id_conflicts_in_the_same_company_are_rejected(
    persona: Persona, app_sessions: sessionmaker[Session], db_settings: Settings
) -> None:
    first = ingest_and_extract(
        persona, app_sessions, db_settings, [extraction_json()], jd_variant("one")
    )
    second = ingest_and_extract(
        persona,
        app_sessions,
        db_settings,
        [extraction_json(external_job_id="EX-2", title="Other role")],
        jd_variant("two"),
    )
    company_id = get_opportunity(persona, first)["company"]["id"]
    assert get_opportunity(persona, second)["company"]["id"] == company_id
    target = get_opportunity(persona, second)

    response = persona.request(
        "PATCH",
        f"{OPPORTUNITIES}/{second}",
        json=patch_body(target, external_job_id="EX-1001"),
    )

    assert response.status_code == 409
    assert response.json() == {"error": {"code": "duplicate_job_id"}}
    assert get_opportunity(persona, second)["external_job_id"] == "EX-2"
    assert get_opportunity(persona, second)["state_version"] == target["state_version"]


def test_company_must_be_the_callers_and_can_be_unlinked(persona: Persona, other: Persona) -> None:
    opportunity_id = ingest_ok(persona, SYNTHETIC_JD)
    opportunity = get_opportunity(persona, opportunity_id)
    mine = persona.request("POST", COMPANIES, json={"name": "Mine Corp"}).json()
    foreign = other.request("POST", COMPANIES, json={"name": "Foreign Corp"}).json()

    rejected = persona.request(
        "PATCH",
        f"{OPPORTUNITIES}/{opportunity_id}",
        json=patch_body(opportunity, company_id=foreign["id"]),
    )
    linked = persona.request(
        "PATCH",
        f"{OPPORTUNITIES}/{opportunity_id}",
        json=patch_body(opportunity, company_id=mine["id"]),
    ).json()
    unlinked = persona.request(
        "PATCH",
        f"{OPPORTUNITIES}/{opportunity_id}",
        json=patch_body(linked, company_id=None),
    ).json()

    assert rejected.status_code == 404
    assert rejected.json() == {"error": {"code": "not_found"}}
    assert linked["company"]["name"] == "Mine Corp"
    assert unlinked["company"] is None


@pytest.mark.parametrize(
    "fields",
    [
        {"workplace_type": None},
        {"workplace_type": "office"},
        {"locations": None},
        {"locations": {"items": [{"country": "ZZ"}]}},
        {"locations": {"items": [{"city": "x"}] * 11}},
        {"source_url": "javascript:alert(1)"},
        {"title": "t" * 301},
        {"unknown_field": 1},
    ],
)
def test_invalid_edits_are_rejected(persona: Persona, fields: dict[str, Any]) -> None:
    opportunity_id = ingest_ok(persona, SYNTHETIC_JD)
    opportunity = get_opportunity(persona, opportunity_id)

    response = persona.request(
        "PATCH", f"{OPPORTUNITIES}/{opportunity_id}", json=patch_body(opportunity, **fields)
    )

    assert response.status_code == 422
    assert get_opportunity(persona, opportunity_id)["state_version"] == opportunity["state_version"]


def test_priority_changes_do_not_move_content_updated_at(
    persona: Persona, owner_session: Session
) -> None:
    opportunity_id = ingest_ok(persona, SYNTHETIC_JD)
    before = get_opportunity(persona, opportunity_id)

    changed = persona.request(
        "PATCH", f"{OPPORTUNITIES}/{opportunity_id}/priority", json={"priority": "high"}
    )
    same = persona.request(
        "PATCH", f"{OPPORTUNITIES}/{opportunity_id}/priority", json={"priority": "high"}
    )
    invalid = persona.request(
        "PATCH", f"{OPPORTUNITIES}/{opportunity_id}/priority", json={"priority": "urgent"}
    )

    assert changed.status_code == 200
    assert changed.json()["priority"] == "high"
    assert changed.json()["content_updated_at"] == before["content_updated_at"]
    assert changed.json()["state_version"] == before["state_version"] + 1
    assert same.json()["state_version"] == before["state_version"] + 1
    assert invalid.status_code == 422
    priority_events = [
        event
        for event in events(owner_session, opportunity_id)
        if event.event_type == "OPPORTUNITY_PRIORITY_CHANGED"
    ]
    assert len(priority_events) == 1
    assert priority_events[0].payload["from_priority"] == "normal"
    assert priority_events[0].payload["to_priority"] == "high"


def test_qualifications_can_be_added_edited_and_deleted_with_content_bumps(
    persona: Persona, owner_session: Session
) -> None:
    opportunity_id = ingest_ok(persona, SYNTHETIC_JD)
    start = get_opportunity(persona, opportunity_id)

    created = persona.request(
        "POST",
        f"{OPPORTUNITIES}/{opportunity_id}/qualifications",
        json={
            "kind": "minimum",
            "text_verbatim": "  My   own  requirement ",
            "category": "skill",
            "skill_keys": [" Rust ", "rust", "Go"],
            "min_years": 3,
            "is_hard_constraint": True,
        },
    )
    second = persona.request(
        "POST",
        f"{OPPORTUNITIES}/{opportunity_id}/qualifications",
        json={"kind": "preferred", "text_verbatim": "Another", "category": "other"},
    )

    assert created.status_code == 201, created.text
    row = created.json()
    assert row["origin"] == "user"
    assert row["text_verbatim"] == "My own requirement"
    assert row["skill_keys"] == ["rust", "go"]
    assert (row["ordinal"], second.json()["ordinal"]) == (0, 1)
    after_add = get_opportunity(persona, opportunity_id)
    assert moment(after_add["content_updated_at"]) > moment(start["content_updated_at"])
    assert [item["id"] for item in after_add["qualifications"]] == [row["id"], second.json()["id"]]

    patched = persona.request(
        "PATCH",
        f"/api/v1/qualifications/{row['id']}",
        json={"kind": "preferred", "category": "domain", "min_years": None, "ordinal": 5},
    )

    assert patched.status_code == 200
    assert patched.json()["kind"] == "preferred"
    assert patched.json()["min_years"] is None
    assert patched.json()["ordinal"] == 5
    assert patched.json()["text_verbatim"] == "My own requirement"
    after_patch = get_opportunity(persona, opportunity_id)
    assert moment(after_patch["content_updated_at"]) > moment(after_add["content_updated_at"])
    assert [item["id"] for item in after_patch["qualifications"]] == [
        second.json()["id"],
        row["id"],
    ]

    no_op = persona.request(
        "PATCH", f"/api/v1/qualifications/{row['id']}", json={"kind": "preferred"}
    )
    assert no_op.status_code == 200
    assert (
        get_opportunity(persona, opportunity_id)["content_updated_at"]
        == after_patch["content_updated_at"]
    )

    deleted = persona.request("DELETE", f"/api/v1/qualifications/{row['id']}")
    assert deleted.status_code == 204
    after_delete = get_opportunity(persona, opportunity_id)
    assert len(after_delete["qualifications"]) == 1
    assert moment(after_delete["content_updated_at"]) > moment(after_patch["content_updated_at"])
    fields = [
        event.payload["fields"]
        for event in events(owner_session, opportunity_id)
        if event.event_type == "OPPORTUNITY_CONTENT_EDITED"
    ]
    assert fields == [["qualifications"]] * 4
    assert persona.request("DELETE", f"/api/v1/qualifications/{row['id']}").status_code == 404


def test_verbatim_text_can_never_be_edited_through_the_api(persona: Persona) -> None:
    opportunity_id = ingest_ok(persona, SYNTHETIC_JD)
    created = persona.request(
        "POST",
        f"{OPPORTUNITIES}/{opportunity_id}/qualifications",
        json={"kind": "minimum", "text_verbatim": "Original", "category": "skill"},
    ).json()

    response = persona.request(
        "PATCH", f"/api/v1/qualifications/{created['id']}", json={"text_verbatim": "Changed"}
    )

    assert response.status_code == 422
    assert get_opportunity(persona, opportunity_id)["qualifications"][0]["text_verbatim"] == (
        "Original"
    )


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "required", "text_verbatim": "x", "category": "skill"},
        {"kind": "minimum", "text_verbatim": "x", "category": "perk"},
        {"kind": "minimum", "text_verbatim": "   ", "category": "skill"},
        {"kind": "minimum", "text_verbatim": "x" * 1001, "category": "skill"},
        {"kind": "minimum", "text_verbatim": "x", "category": "skill", "min_years": 51},
        {"kind": "minimum", "text_verbatim": "x", "category": "skill", "origin": "extracted"},
    ],
)
def test_invalid_qualifications_are_rejected(persona: Persona, body: dict[str, Any]) -> None:
    opportunity_id = ingest_ok(persona, SYNTHETIC_JD)

    response = persona.request(
        "POST", f"{OPPORTUNITIES}/{opportunity_id}/qualifications", json=body
    )

    assert response.status_code == 422


def test_company_create_edit_and_priority(persona: Persona, owner_session: Session) -> None:
    created = persona.request(
        "POST",
        COMPANIES,
        json={
            "name": "  Example   Inc. ",
            "aliases": ["Ex Co", "ex co"],
            "domains": ["https://www.Example.test/careers"],
            "careers_url": "https://example.test/careers",
            "notes": "my note",
            "strategic_priority": "high",
        },
    )

    assert created.status_code == 201, created.text
    company = created.json()
    assert company["name"] == "Example Inc."
    assert company["normalized_name"] == "example"
    assert company["aliases"] == ["Ex Co"]
    assert company["domains"] == ["example.test"]
    assert company["origin"] == "user"
    assert company["strategic_priority"] == "high"
    taken = persona.request("POST", COMPANIES, json={"name": "EXAMPLE corporation"})
    assert taken.status_code == 409
    assert taken.json() == {"error": {"code": "company_name_taken"}}

    renamed = persona.request(
        "PATCH",
        f"{COMPANIES}/{company['id']}",
        json={
            "name": "Widget Works LLC",
            "aliases": ["WW"],
            "domains": ["widgetworks.test"],
            "careers_url": None,
            "notes": "",
            "strategic_priority": "low",
        },
    )

    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["normalized_name"] == "widget works"
    assert renamed.json()["careers_url"] is None
    assert renamed.json()["strategic_priority"] == "low"
    assert renamed.json()["aliases"] == ["WW"]
    recorded = events(owner_session, company["id"])
    assert [event.event_type for event in recorded] == [
        "COMPANY_CREATED",
        "COMPANY_PRIORITY_CHANGED",
    ]
    assert recorded[1].payload["from_priority"] == "high"
    assert recorded[1].payload["to_priority"] == "low"
    assert "Widget" not in str(recorded[1].payload)


def test_company_rename_to_a_taken_name_is_rejected_and_same_name_is_allowed(
    persona: Persona,
) -> None:
    first = persona.request("POST", COMPANIES, json={"name": "Alpha Ltd"}).json()
    second = persona.request("POST", COMPANIES, json={"name": "Beta Ltd"}).json()

    conflict = persona.request("PATCH", f"{COMPANIES}/{second['id']}", json={"name": "alpha"})
    same = persona.request("PATCH", f"{COMPANIES}/{first['id']}", json={"name": "ALPHA, Inc"})

    assert conflict.status_code == 409
    assert conflict.json() == {"error": {"code": "company_name_taken"}}
    assert same.status_code == 200
    assert same.json()["name"] == "ALPHA, Inc"


@pytest.mark.parametrize(
    "body",
    [
        {"name": "   "},
        {"name": "!!!"},
        {"name": "Ok", "domains": ["not a domain"]},
        {"name": "Ok", "careers_url": "ftp://example.test"},
        {"name": "Ok", "strategic_priority": "urgent"},
        {"name": "Ok", "aliases": ["a"] * 21},
        {"name": "Ok", "unknown": 1},
    ],
)
def test_invalid_companies_are_rejected(persona: Persona, body: dict[str, Any]) -> None:
    assert persona.request("POST", COMPANIES, json=body).status_code == 422


def test_company_detail_counts_opportunities_by_status(
    persona: Persona, app_sessions: sessionmaker[Session], db_settings: Settings
) -> None:
    opportunity_id = ingest_and_extract(persona, app_sessions, db_settings, [extraction_json()])
    company_id = get_opportunity(persona, opportunity_id)["company"]["id"]

    detail = persona.request("GET", f"{COMPANIES}/{company_id}").json()
    listed = persona.request("GET", COMPANIES).json()

    assert detail["opportunity_counts"] == {
        "new": 1,
        "saved": 0,
        "skipped": 0,
        "applied": 0,
        "closed": 0,
    }
    assert [item["id"] for item in listed] == [company_id]
    assert "opportunity_counts" not in listed[0]


def test_unauthenticated_clients_cannot_reach_the_new_routes(app: FastAPI) -> None:
    client = new_client(app)

    assert client.get(OPPORTUNITIES).status_code == 401
    assert client.get(COMPANIES).status_code == 401
