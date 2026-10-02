from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy.orm import Session

from app.resumes.router import attachment_disposition
from tests.auth.fake_idp import FakeIdentityProvider
from tests.db.auth_helpers import Persona, make_persona
from tests.db.resume_helpers import create_lane, lane_updated_at, upload
from tests.synthetic import synthetic_pdf

pytestmark = pytest.mark.db


@pytest.fixture
def persona(app: FastAPI, idp: FakeIdentityProvider) -> Persona:
    return make_persona(app, idp, "a")


@pytest.fixture
def other(app: FastAPI, idp: FakeIdentityProvider) -> Persona:
    return make_persona(app, idp, "b")


def new_resume(persona: Persona, tag: str, **kwargs: Any) -> dict[str, Any]:
    response = upload(persona, synthetic_pdf(tag), f"{tag}.pdf", **kwargs)
    assert response.status_code == 202, response.text
    body: dict[str, Any] = response.json()
    return body


def patch_lane(persona: Persona, lane_id: str, **body: Any) -> Any:
    return persona.request("PATCH", f"/api/v1/lanes/{lane_id}", json=body)


def assign(persona: Persona, resume_id: str, lane_id: str | None) -> Any:
    return persona.request("PATCH", f"/api/v1/resumes/{resume_id}", json={"lane_id": lane_id})


def test_list_and_detail_describe_the_callers_resumes(persona: Persona) -> None:
    created = new_resume(persona, "one")

    listing = persona.client.get("/api/v1/resumes").json()
    detail = persona.client.get(f"/api/v1/resumes/{created['id']}").json()

    assert [row["id"] for row in listing] == [created["id"]]
    assert listing[0]["extraction_status"] == "pending"
    assert listing[0]["archived"] is False
    assert detail["parsed_outline"] is None
    assert "extracted_text" not in detail
    assert "storage_key" not in detail
    assert "sha256" not in detail


def test_label_and_lane_are_the_only_editable_fields(persona: Persona) -> None:
    created = new_resume(persona, "one")
    lane = create_lane(persona)

    renamed = persona.request("PATCH", f"/api/v1/resumes/{created['id']}", json={"label": "Main"})
    moved = assign(persona, created["id"], lane["id"])

    assert renamed.json()["label"] == "Main"
    assert moved.json()["lane_id"] == lane["id"]
    for forbidden in (
        {"artifact_id": created["id"]},
        {"storage_key": "x"},
        {"sha256": "x"},
        {"status": "archived"},
        {"original_filename": "x.pdf"},
        {"extracted_text": "x"},
        {"parsed_outline": {}},
    ):
        response = persona.request("PATCH", f"/api/v1/resumes/{created['id']}", json=forbidden)
        assert response.status_code == 422, forbidden


def test_label_cannot_be_blank_or_null(persona: Persona) -> None:
    created = new_resume(persona, "one")

    for label in ("", "   ", None):
        response = persona.request(
            "PATCH", f"/api/v1/resumes/{created['id']}", json={"label": label}
        )
        assert response.status_code == 422


def test_lane_assignment_requires_an_active_lane_of_the_same_user(
    persona: Persona, other: Persona
) -> None:
    created = new_resume(persona, "one")
    foreign = create_lane(other, "Foreign")
    archived = create_lane(persona, "Old")
    persona.request("POST", f"/api/v1/lanes/{archived['id']}/archive")

    assert assign(persona, created["id"], foreign["id"]).status_code == 404
    inactive = assign(persona, created["id"], archived["id"])
    assert inactive.status_code == 422
    assert inactive.json() == {"error": {"code": "lane_not_active"}}


def test_archive_and_unarchive_a_resume(persona: Persona) -> None:
    created = new_resume(persona, "one")

    archived = persona.request("POST", f"/api/v1/resumes/{created['id']}/archive").json()
    again = persona.request("POST", f"/api/v1/resumes/{created['id']}/archive").json()
    restored = persona.request("POST", f"/api/v1/resumes/{created['id']}/unarchive").json()

    assert archived["status"] == "archived"
    assert archived["archived"] is True
    assert archived["archived_at"] is not None
    assert again["status"] == "archived"
    assert restored["status"] == "active"
    assert restored["archived_at"] is None


def test_download_streams_the_original_bytes_as_an_attachment(persona: Persona) -> None:
    content = synthetic_pdf("download")
    created = upload(persona, content, "résumé v1.pdf").json()

    response = persona.client.get(f"/api/v1/resumes/{created['id']}/file")

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["x-content-type-options"] == "nosniff"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert 'filename="r_sum_ v1.pdf"' in disposition
    assert "filename*=UTF-8''r%C3%A9sum%C3%A9%20v1.pdf" in disposition
    assert response.headers["cache-control"] == "private, no-store"


def test_attachment_header_neutralizes_quotes_and_separators() -> None:
    header = attachment_disposition('a"b;c\r\nd.pdf')

    assert header.startswith('attachment; filename="a_b_c__d.pdf";')
    assert '"' not in header.split("filename*=")[1]
    assert "\r" not in header
    assert "\n" not in header


def test_archived_resumes_can_still_be_downloaded(persona: Persona) -> None:
    content = synthetic_pdf("archived-download")
    created = upload(persona, content).json()
    persona.request("POST", f"/api/v1/resumes/{created['id']}/archive")

    assert persona.client.get(f"/api/v1/resumes/{created['id']}/file").content == content


def test_no_route_can_modify_or_replace_a_stored_file(app: FastAPI) -> None:
    paths = app.openapi()["paths"]
    resume_methods = {
        path: set(operations) for path, operations in paths.items() if "/resumes" in path
    }

    assert resume_methods["/api/v1/resumes/{resume_id}/file"] == {"get"}
    assert resume_methods["/api/v1/resumes/{resume_id}"] == {"get", "patch"}
    assert resume_methods["/api/v1/resumes"] == {"get", "post"}
    assert not any(
        method in {"put", "delete"} for methods in resume_methods.values() for method in methods
    )


def test_lane_create_list_and_validation(persona: Persona) -> None:
    lane = create_lane(
        persona,
        "Platform",
        description="Infrastructure roles",
        emphasis_notes="Lead with reliability work",
        target_role_labels=["Platform Engineer", "SRE"],
    )

    listing = persona.client.get("/api/v1/lanes").json()

    assert [row["id"] for row in listing] == [lane["id"]]
    assert listing[0]["target_role_labels"] == ["Platform Engineer", "SRE"]
    assert listing[0]["status"] == "active"
    assert listing[0]["default_resume_id"] is None
    for bad in (
        {"name": ""},
        {"name": "x" * 81},
        {"name": "ok", "unknown": 1},
        {"name": "ok", "target_role_labels": ["a"] * 21},
        {"name": "ok", "default_resume_id": None},
    ):
        assert persona.request("POST", "/api/v1/lanes", json=bad).status_code == 422, bad


def test_active_lane_names_are_unique_per_user_ignoring_case(
    persona: Persona, other: Persona
) -> None:
    first = create_lane(persona, "Platform")
    create_lane(other, "platform")

    duplicate = persona.request("POST", "/api/v1/lanes", json={"name": "PLATFORM"})
    second = create_lane(persona, "Data")
    rename = patch_lane(persona, second["id"], name="platform")

    assert duplicate.status_code == 409
    assert duplicate.json() == {"error": {"code": "lane_name_taken"}}
    assert rename.status_code == 409
    assert patch_lane(persona, first["id"], name="Platform").status_code == 200

    persona.request("POST", f"/api/v1/lanes/{first['id']}/archive")
    reused = create_lane(persona, "Platform")
    blocked = persona.request("POST", f"/api/v1/lanes/{first['id']}/unarchive")

    assert reused["id"] != first["id"]
    assert blocked.status_code == 409


def test_lane_edit_archive_and_unarchive(persona: Persona) -> None:
    lane = create_lane(persona)

    edited = patch_lane(persona, lane["id"], description="New", target_role_labels=["A"]).json()
    archived = persona.request("POST", f"/api/v1/lanes/{lane['id']}/archive").json()
    restored = persona.request("POST", f"/api/v1/lanes/{lane['id']}/unarchive").json()

    assert edited["description"] == "New"
    assert edited["target_role_labels"] == ["A"]
    assert archived["status"] == "archived"
    assert restored["status"] == "active"
    for field in ("name", "description", "emphasis_notes", "target_role_labels"):
        assert patch_lane(persona, lane["id"], **{field: None}).status_code == 422


def test_default_resume_must_be_an_active_resume_assigned_to_the_lane(
    persona: Persona, other: Persona
) -> None:
    lane = create_lane(persona)
    elsewhere = create_lane(persona, "Elsewhere")
    inside = new_resume(persona, "inside", lane_id=lane["id"])
    outside = new_resume(persona, "outside")
    in_other_lane = new_resume(persona, "other-lane", lane_id=elsewhere["id"])
    archived = new_resume(persona, "archived", lane_id=lane["id"])
    persona.request("POST", f"/api/v1/resumes/{archived['id']}/archive")
    foreign = new_resume(other, "foreign")

    ok = patch_lane(persona, lane["id"], default_resume_id=inside["id"])

    assert ok.status_code == 200
    assert ok.json()["default_resume_id"] == inside["id"]
    for ineligible in (outside, in_other_lane, archived):
        response = patch_lane(persona, lane["id"], default_resume_id=ineligible["id"])
        assert response.status_code == 422, ineligible
        assert response.json() == {"error": {"code": "invalid_default_resume"}}
    assert patch_lane(persona, lane["id"], default_resume_id=foreign["id"]).status_code == 404
    assert (
        patch_lane(persona, lane["id"], default_resume_id=None).json()["default_resume_id"] is None
    )


def test_archiving_a_default_resume_clears_the_default(persona: Persona) -> None:
    lane = create_lane(persona)
    resume = new_resume(persona, "one", lane_id=lane["id"])
    patch_lane(persona, lane["id"], default_resume_id=resume["id"])

    persona.request("POST", f"/api/v1/resumes/{resume['id']}/archive")

    lanes = persona.client.get("/api/v1/lanes").json()
    assert lanes[0]["default_resume_id"] is None


def test_moving_a_default_resume_out_of_its_lane_clears_the_default(persona: Persona) -> None:
    lane = create_lane(persona)
    resume = new_resume(persona, "one", lane_id=lane["id"])
    patch_lane(persona, lane["id"], default_resume_id=resume["id"])

    assign(persona, resume["id"], None)

    assert persona.client.get("/api/v1/lanes").json()[0]["default_resume_id"] is None


def test_every_lane_membership_or_edit_event_bumps_updated_at(
    persona: Persona, owner_session: Session
) -> None:
    lane = create_lane(persona)
    other_lane = create_lane(persona, "Second")
    resume = new_resume(persona, "one")
    lane_id, other_id = lane["id"], other_lane["id"]
    seen = [lane_updated_at(owner_session, lane_id)]

    def bumped(label: str, target: str = lane_id) -> None:
        current = lane_updated_at(owner_session, target)
        assert current > seen[-1], label
        seen.append(current)

    patch_lane(persona, lane_id, description="edited")
    bumped("edit")
    persona.request("POST", f"/api/v1/lanes/{lane_id}/archive")
    bumped("archive")
    persona.request("POST", f"/api/v1/lanes/{lane_id}/unarchive")
    bumped("unarchive")
    assign(persona, resume["id"], lane_id)
    bumped("resume assigned")
    persona.request("POST", f"/api/v1/resumes/{resume['id']}/archive")
    bumped("resume archived while in lane")
    persona.request("POST", f"/api/v1/resumes/{resume['id']}/unarchive")
    bumped("resume unarchived while in lane")
    assign(persona, resume["id"], other_id)
    bumped("resume removed from lane")
    new_resume(persona, "two", lane_id=lane_id)
    bumped("resume created in lane")


def test_unrelated_actions_do_not_bump_a_lane(persona: Persona, owner_session: Session) -> None:
    lane = create_lane(persona)
    before = lane_updated_at(owner_session, lane["id"])

    new_resume(persona, "unassigned")
    persona.request("PUT", "/api/v1/profile", json={"headline": "unrelated"})

    assert lane_updated_at(owner_session, lane["id"]) == before


def test_assigning_to_a_lane_bumps_the_target_and_removal_bumps_the_source(
    persona: Persona, owner_session: Session
) -> None:
    source = create_lane(persona, "Source")
    target = create_lane(persona, "Target")
    resume = new_resume(persona, "one", lane_id=source["id"])
    source_before = lane_updated_at(owner_session, source["id"])
    target_before = lane_updated_at(owner_session, target["id"])

    assign(persona, resume["id"], target["id"])

    assert lane_updated_at(owner_session, source["id"]) > source_before
    assert lane_updated_at(owner_session, target["id"]) > target_before
