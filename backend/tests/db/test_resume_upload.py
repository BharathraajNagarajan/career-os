import hashlib
import uuid

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.artifacts.sniff import DOCX_MAX_MEMBERS, DOCX_MIME
from app.config import Settings
from tests.auth.fake_idp import FakeIdentityProvider
from tests.db.auth_helpers import Persona, make_persona
from tests.db.resume_helpers import create_lane, lane_updated_at, stored_files, upload
from tests.synthetic import synthetic_docx, synthetic_pdf, zip_with

pytestmark = pytest.mark.db


@pytest.fixture
def persona(app: FastAPI, idp: FakeIdentityProvider) -> Persona:
    return make_persona(app, idp, "a")


def artifact_count(owner: Session) -> int:
    owner.rollback()
    return owner.execute(text("SELECT count(*) FROM artifacts")).scalar_one()


def test_pdf_upload_is_accepted_stored_and_queued(
    persona: Persona, owner_session: Session, db_settings: Settings
) -> None:
    content = synthetic_pdf("upload-one")

    response = upload(persona, content, "My Resume v3.pdf")

    assert response.status_code == 202
    body = response.json()
    assert body["extraction_status"] == "pending"
    assert body["label"] == "My Resume v3"
    assert body["original_filename"] == "My Resume v3.pdf"
    assert body["mime_type"] == "application/pdf"
    assert body["status"] == "active"
    assert body["lane_id"] is None
    artifact = owner_session.execute(
        text("SELECT id, user_id, kind, storage_key, sha256, byte_size FROM artifacts")
    ).one()
    assert artifact.user_id == persona.user_id
    assert artifact.kind == "resume_file"
    assert artifact.storage_key == f"users/{persona.user_id}/artifacts/{artifact.id}"
    assert bytes(artifact.sha256) == hashlib.sha256(content).digest()
    assert artifact.byte_size == len(content)
    files = stored_files(db_settings.artifact_storage_dir)
    assert [path.read_bytes() for path in files] == [content]
    job = owner_session.execute(
        text("SELECT kind, user_id, unique_key, payload, status FROM jobs")
    ).one()
    assert job.kind == "parse_resume"
    assert job.user_id == persona.user_id
    assert job.unique_key == f"parse_resume:{artifact.id}"
    assert job.payload == {"artifact_id": str(artifact.id), "resume_id": body["id"]}
    assert job.status == "queued"


def test_docx_upload_is_accepted(persona: Persona) -> None:
    response = upload(persona, synthetic_docx("upload-two"), "resume.docx")

    assert response.status_code == 202
    assert response.json()["mime_type"] == DOCX_MIME


def test_content_decides_the_type_not_the_name_or_content_type(persona: Persona) -> None:
    pdf_named_txt = upload(persona, synthetic_pdf("a"), "resume.txt", content_type="text/plain")
    text_named_pdf = upload(
        persona, b"just some plain text", "resume.pdf", content_type="application/pdf"
    )

    assert pdf_named_txt.status_code == 202
    assert pdf_named_txt.json()["mime_type"] == "application/pdf"
    assert text_named_pdf.status_code == 415
    assert text_named_pdf.json() == {"error": {"code": "unsupported_file_type"}}


def test_unsupported_upload_stores_nothing(
    persona: Persona, owner_session: Session, db_settings: Settings
) -> None:
    response = upload(persona, b"plain text", "resume.txt")

    assert response.status_code == 415
    assert artifact_count(owner_session) == 0
    assert stored_files(db_settings.artifact_storage_dir) == []


def test_duplicate_content_is_rejected_with_the_existing_resume(
    persona: Persona, owner_session: Session, db_settings: Settings
) -> None:
    content = synthetic_pdf("dup")
    first = upload(persona, content, "first.pdf")

    second = upload(persona, content, "renamed.pdf")

    assert second.status_code == 409
    assert second.json() == {"error": {"code": "duplicate_resume", "resume_id": first.json()["id"]}}
    assert artifact_count(owner_session) == 1
    assert len(stored_files(db_settings.artifact_storage_dir)) == 1


def test_the_same_file_can_be_uploaded_by_different_users(
    app: FastAPI, idp: FakeIdentityProvider, persona: Persona, db_settings: Settings
) -> None:
    other = make_persona(app, idp, "b")
    content = synthetic_pdf("shared")

    assert upload(persona, content).status_code == 202
    assert upload(other, content).status_code == 202
    assert len(stored_files(db_settings.artifact_storage_dir)) == 2


def test_oversized_upload_is_rejected_without_storing(
    persona: Persona, owner_session: Session, db_settings: Settings
) -> None:
    content = b"%PDF-" + b"0" * db_settings.resume_max_bytes

    response = upload(persona, content)

    assert response.status_code == 413
    assert response.json() == {"error": {"code": "resume_too_large"}}
    assert artifact_count(owner_session) == 0
    assert stored_files(db_settings.artifact_storage_dir) == []


def test_oversized_chunked_upload_without_content_length_is_rejected(
    persona: Persona, db_settings: Settings
) -> None:
    boundary = "synthetic-boundary"
    head = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="a.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode()

    def body() -> object:
        yield head + b"%PDF-"
        for _ in range(db_settings.resume_max_bytes // 65536 + 3):
            yield b"0" * 65536
        yield f"\r\n--{boundary}--\r\n".encode()

    response = persona.request(
        "POST",
        "/api/v1/resumes",
        content=body(),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )

    assert response.status_code == 413
    assert stored_files(db_settings.artifact_storage_dir) == []


def test_a_file_exactly_at_the_limit_is_accepted(persona: Persona, db_settings: Settings) -> None:
    base = synthetic_pdf("limit")
    content = base + b"\n%" + b"0" * (db_settings.resume_max_bytes - len(base) - 2)
    assert len(content) == db_settings.resume_max_bytes

    assert upload(persona, content).status_code == 202


def test_zip_bomb_like_docx_is_rejected(persona: Persona, db_settings: Settings) -> None:
    members = {f"part{index}.xml": b"x" for index in range(DOCX_MAX_MEMBERS)}
    members["word/document.xml"] = b"<w/>"

    response = upload(persona, zip_with(members), "bomb.docx")

    assert response.status_code == 422
    assert response.json() == {"error": {"code": "unsafe_document"}}
    assert stored_files(db_settings.artifact_storage_dir) == []


def test_a_zip_that_is_not_a_docx_is_unsupported(persona: Persona) -> None:
    response = upload(persona, zip_with({"notes.txt": b"hello"}), "archive.docx")

    assert response.status_code == 415


def test_malformed_requests_are_rejected_cleanly(persona: Persona) -> None:
    as_json = persona.request("POST", "/api/v1/resumes", json={"file": "x"})
    no_file = persona.request("POST", "/api/v1/resumes", files={"label": (None, "x")})
    two_files = persona.request(
        "POST",
        "/api/v1/resumes",
        files=[
            ("file", ("a.pdf", synthetic_pdf("one"), "application/pdf")),
            ("file", ("b.pdf", synthetic_pdf("two"), "application/pdf")),
        ],
    )

    assert as_json.status_code == 400
    assert no_file.status_code == 422
    assert no_file.json() == {"error": {"code": "file_required"}}
    assert two_files.status_code == 400


def test_upload_needs_csrf(persona: Persona) -> None:
    response = persona.client.post(
        "/api/v1/resumes", files={"file": ("a.pdf", synthetic_pdf("a"), "application/pdf")}
    )

    assert response.status_code == 403


def test_stored_filename_is_sanitized(persona: Persona) -> None:
    response = upload(persona, synthetic_pdf("name"), "../../etc/passwd.pdf")

    assert response.json()["original_filename"] == "passwd.pdf"


def test_label_can_be_supplied_at_upload(persona: Persona) -> None:
    response = upload(persona, synthetic_pdf("label"), "file.pdf", label="  Backend focus  ")

    assert response.json()["label"] == "Backend focus"


def test_orphan_file_is_removed_when_the_transaction_fails(
    persona: Persona,
    owner_session: Session,
    db_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_enqueue(*_: object, **__: object) -> uuid.UUID:
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr("app.resumes.service.enqueue", failing_enqueue)

    with pytest.raises(RuntimeError, match="queue unavailable"):
        upload(persona, synthetic_pdf("orphan"))

    assert stored_files(db_settings.artifact_storage_dir) == []
    assert artifact_count(owner_session) == 0


def test_upload_into_a_lane_bumps_the_lane(persona: Persona, owner_session: Session) -> None:
    lane = create_lane(persona)
    before = lane_updated_at(owner_session, lane["id"])

    response = upload(persona, synthetic_pdf("lane"), lane_id=lane["id"])

    assert response.status_code == 202
    assert response.json()["lane_id"] == lane["id"]
    assert lane_updated_at(owner_session, lane["id"]) > before


def test_upload_lane_must_be_the_callers_active_lane(
    app: FastAPI, idp: FakeIdentityProvider, persona: Persona, db_settings: Settings
) -> None:
    other = make_persona(app, idp, "b")
    foreign_lane = create_lane(other)
    archived = create_lane(persona, "Old")
    persona.request("POST", f"/api/v1/lanes/{archived['id']}/archive")

    foreign = upload(persona, synthetic_pdf("a"), lane_id=foreign_lane["id"])
    inactive = upload(persona, synthetic_pdf("b"), lane_id=archived["id"])
    malformed = upload(persona, synthetic_pdf("c"), lane_id="not-a-uuid")

    assert foreign.status_code == 404
    assert inactive.status_code == 422
    assert inactive.json() == {"error": {"code": "lane_not_active"}}
    assert malformed.status_code == 422
    assert stored_files(db_settings.artifact_storage_dir) == []
