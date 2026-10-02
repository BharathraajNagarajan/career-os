import re
import uuid
from collections.abc import Iterator
from typing import Annotated, Any, BinaryIO
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.artifacts.sniff import UploadRejected
from app.artifacts.storage import CHUNK_SIZE, StorageAdapter
from app.auth.deps import current_auth, get_db_session, verify_csrf
from app.auth.service import AuthContext
from app.config import Settings
from app.core.errors import ApiError, ErrorResponse
from app.resumes.schemas import (
    LaneCreate,
    LanePatch,
    LaneResponse,
    ResumeDetail,
    ResumePatch,
    ResumeSummary,
)
from app.resumes.service import LaneService, ResumeService
from app.resumes.upload import receive_upload

router = APIRouter(
    prefix="/api/v1",
    tags=["resumes"],
    dependencies=[Depends(verify_csrf)],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)

NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"model": ErrorResponse}}
UPLOAD_SCHEMA = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {
                        "file": {"type": "string", "format": "binary"},
                        "label": {"type": "string", "maxLength": 120},
                        "lane_id": {"type": "string", "format": "uuid"},
                    },
                }
            }
        },
    }
}


def get_settings_from_app(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_storage(request: Request) -> StorageAdapter:
    storage: StorageAdapter = request.app.state.storage
    return storage


Auth = Annotated[AuthContext, Depends(current_auth)]
DbSession = Annotated[Session, Depends(get_db_session)]
AppSettings = Annotated[Settings, Depends(get_settings_from_app)]
Storage = Annotated[StorageAdapter, Depends(get_storage)]


def resume_service(session: DbSession, storage: Storage) -> ResumeService:
    return ResumeService(session, storage)


def lane_service(session: DbSession) -> LaneService:
    return LaneService(session)


Resumes = Annotated[ResumeService, Depends(resume_service)]
Lanes = Annotated[LaneService, Depends(lane_service)]


def parse_lane_id(raw: str | None) -> uuid.UUID | None:
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise ApiError(422, "invalid_lane_id") from exc


@router.post(
    "/resumes",
    status_code=202,
    response_model=ResumeSummary,
    openapi_extra=UPLOAD_SCHEMA,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        415: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def upload_resume(
    request: Request, auth: Auth, service: Resumes, settings: AppSettings
) -> ResumeSummary:
    received = await receive_upload(request, max_bytes=settings.resume_max_bytes)
    try:
        lane_id = parse_lane_id(received.fields.get("lane_id"))
        resume, artifact = await run_in_threadpool(
            service.upload,
            user_id=auth.user_id,
            spool=received.spool,
            size=received.size,
            sha256=received.sha256,
            original_filename=received.filename,
            label=received.fields.get("label"),
            lane_id=lane_id,
        )
    except UploadRejected as exc:
        raise ApiError(exc.status_code, exc.code) from exc
    finally:
        received.spool.close()
    return ResumeSummary.build(resume, artifact)


@router.get("/resumes", response_model=list[ResumeSummary])
def list_resumes(auth: Auth, service: Resumes) -> list[ResumeSummary]:
    return [
        ResumeSummary.build(resume, artifact)
        for resume, artifact in service.list(user_id=auth.user_id)
    ]


@router.get("/resumes/{resume_id}", response_model=ResumeDetail, responses=NOT_FOUND)
def get_resume(resume_id: uuid.UUID, auth: Auth, service: Resumes) -> ResumeDetail:
    resume, artifact = service.get(user_id=auth.user_id, resume_id=resume_id)
    return ResumeDetail.build_detail(resume, artifact)


@router.patch(
    "/resumes/{resume_id}",
    response_model=ResumeSummary,
    responses={**NOT_FOUND, 422: {"model": ErrorResponse}},
)
def patch_resume(
    resume_id: uuid.UUID, body: ResumePatch, auth: Auth, service: Resumes
) -> ResumeSummary:
    resume, artifact = service.patch(user_id=auth.user_id, resume_id=resume_id, data=body)
    return ResumeSummary.build(resume, artifact)


@router.post("/resumes/{resume_id}/archive", response_model=ResumeSummary, responses=NOT_FOUND)
def archive_resume(resume_id: uuid.UUID, auth: Auth, service: Resumes) -> ResumeSummary:
    resume, artifact = service.set_archived(
        user_id=auth.user_id, resume_id=resume_id, archived=True
    )
    return ResumeSummary.build(resume, artifact)


@router.post("/resumes/{resume_id}/unarchive", response_model=ResumeSummary, responses=NOT_FOUND)
def unarchive_resume(resume_id: uuid.UUID, auth: Auth, service: Resumes) -> ResumeSummary:
    resume, artifact = service.set_archived(
        user_id=auth.user_id, resume_id=resume_id, archived=False
    )
    return ResumeSummary.build(resume, artifact)


def attachment_disposition(filename: str) -> str:
    fallback = re.sub(r"[^A-Za-z0-9._ -]", "_", filename)
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"


def stream_file(handle: BinaryIO) -> Iterator[bytes]:
    try:
        while chunk := handle.read(CHUNK_SIZE):
            yield chunk
    finally:
        handle.close()


@router.get(
    "/resumes/{resume_id}/file",
    response_class=StreamingResponse,
    responses={**NOT_FOUND, 200: {"content": {"application/octet-stream": {}}}},
)
def download_resume_file(
    resume_id: uuid.UUID, auth: Auth, service: Resumes, storage: Storage
) -> StreamingResponse:
    _, artifact = service.get(user_id=auth.user_id, resume_id=resume_id)
    try:
        handle = storage.open(artifact.storage_key)
    except FileNotFoundError as exc:
        raise ApiError(404, "file_missing") from exc
    return StreamingResponse(
        stream_file(handle),
        media_type=artifact.mime_type,
        headers={
            "Content-Disposition": attachment_disposition(artifact.original_filename),
            "Content-Length": str(artifact.byte_size),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/lanes", response_model=list[LaneResponse])
def list_lanes(auth: Auth, service: Lanes) -> list[LaneResponse]:
    return [LaneResponse.build(lane) for lane in service.list(user_id=auth.user_id)]


@router.post(
    "/lanes",
    status_code=201,
    response_model=LaneResponse,
    responses={409: {"model": ErrorResponse}},
)
def create_lane(body: LaneCreate, auth: Auth, service: Lanes) -> LaneResponse:
    return LaneResponse.build(service.create(user_id=auth.user_id, data=body))


@router.patch(
    "/lanes/{lane_id}",
    response_model=LaneResponse,
    responses={**NOT_FOUND, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def patch_lane(lane_id: uuid.UUID, body: LanePatch, auth: Auth, service: Lanes) -> LaneResponse:
    return LaneResponse.build(service.patch(user_id=auth.user_id, lane_id=lane_id, data=body))


@router.post(
    "/lanes/{lane_id}/archive",
    response_model=LaneResponse,
    responses=NOT_FOUND,
)
def archive_lane(lane_id: uuid.UUID, auth: Auth, service: Lanes) -> LaneResponse:
    return LaneResponse.build(
        service.set_archived(user_id=auth.user_id, lane_id=lane_id, archived=True)
    )


@router.post(
    "/lanes/{lane_id}/unarchive",
    response_model=LaneResponse,
    responses={**NOT_FOUND, 409: {"model": ErrorResponse}},
)
def unarchive_lane(lane_id: uuid.UUID, auth: Auth, service: Lanes) -> LaneResponse:
    return LaneResponse.build(
        service.set_archived(user_id=auth.user_id, lane_id=lane_id, archived=False)
    )
