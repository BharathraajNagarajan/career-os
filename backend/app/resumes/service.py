import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import BinaryIO

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.artifacts.sniff import default_label, sanitize_filename, sniff
from app.artifacts.storage import StorageAdapter, artifact_key
from app.core.errors import ApiError
from app.core.ids import new_id
from app.db.models import (
    Artifact,
    ArtifactKind,
    LaneStatus,
    Resume,
    ResumeLane,
    ResumeStatus,
)
from app.db.tenancy import resolve_owned
from app.jobs.queue import enqueue
from app.resumes.parse_job import PARSE_RESUME_JOB, ParseResumePayload, parse_unique_key
from app.resumes.repository import ArtifactRepository, LaneRepository, ResumeRepository
from app.resumes.schemas import LaneCreate, LanePatch, ResumePatch


class ResumeService:
    def __init__(self, session: Session, storage: StorageAdapter) -> None:
        self.session = session
        self.storage = storage
        self.artifacts = ArtifactRepository(session)
        self.resumes = ResumeRepository(session)
        self.lanes = LaneRepository(session)

    def upload(
        self,
        *,
        user_id: uuid.UUID,
        spool: BinaryIO,
        size: int,
        sha256: bytes,
        original_filename: str | None,
        label: str | None,
        lane_id: uuid.UUID | None,
    ) -> tuple[Resume, Artifact]:
        sniffed = sniff(spool)
        filename = sanitize_filename(original_filename)
        if lane_id is not None:
            self._require_active_lane(user_id=user_id, lane_id=lane_id)
        self._reject_duplicate(user_id=user_id, sha256=sha256)
        artifact_id = new_id()
        key = artifact_key(user_id, artifact_id)
        spool.seek(0)
        self.storage.put(key, spool)
        try:
            artifact = Artifact(
                id=artifact_id,
                user_id=user_id,
                kind=ArtifactKind.RESUME_FILE,
                storage_key=key,
                sha256=sha256,
                mime_type=sniffed.mime_type,
                byte_size=size,
                original_filename=filename,
            )
            self.session.add(artifact)
            self.session.flush()
            resume = Resume(
                user_id=user_id,
                artifact_id=artifact_id,
                label=(label or default_label(filename)).strip()[:120] or default_label(filename),
                lane_id=lane_id,
            )
            self.session.add(resume)
            self.session.flush()
            enqueue(
                self.session,
                kind=PARSE_RESUME_JOB,
                payload=ParseResumePayload(artifact_id=artifact_id, resume_id=resume.id),
                user_id=user_id,
                unique_key=parse_unique_key(artifact_id),
            )
            if lane_id is not None:
                self.lanes.touch(user_id=user_id, lane_id=lane_id)
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            self.storage.delete_prefix(key)
            self._reject_duplicate(user_id=user_id, sha256=sha256)
            raise
        except BaseException:
            self.session.rollback()
            self.storage.delete_prefix(key)
            raise
        return resume, artifact

    def _reject_duplicate(self, *, user_id: uuid.UUID, sha256: bytes) -> None:
        existing = self.artifacts.find_by_hash(
            user_id=user_id, sha256=sha256, kind=ArtifactKind.RESUME_FILE
        )
        if existing is None:
            return
        resume = self.resumes.find_by_artifact(user_id=user_id, artifact_id=existing.id)
        if resume is not None:
            raise ApiError(409, "duplicate_resume", resume_id=resume.id)

    def _require_active_lane(self, *, user_id: uuid.UUID, lane_id: uuid.UUID) -> ResumeLane:
        lane = self.lanes.get(user_id=user_id, id=lane_id)
        if lane.status is not LaneStatus.ACTIVE:
            raise ApiError(422, "lane_not_active")
        return lane

    def list(self, *, user_id: uuid.UUID) -> Sequence[tuple[Resume, Artifact]]:
        return self.resumes.list_with_artifacts(user_id=user_id)

    def get(self, *, user_id: uuid.UUID, resume_id: uuid.UUID) -> tuple[Resume, Artifact]:
        return self.resumes.get_with_artifact(user_id=user_id, id=resume_id)

    def patch(
        self, *, user_id: uuid.UUID, resume_id: uuid.UUID, data: ResumePatch
    ) -> tuple[Resume, Artifact]:
        resume, artifact = self.resumes.get_with_artifact(user_id=user_id, id=resume_id)
        if data.label is not None:
            resume.label = data.label
        if "lane_id" in data.model_fields_set and data.lane_id != resume.lane_id:
            if data.lane_id is not None:
                self._require_active_lane(user_id=user_id, lane_id=data.lane_id)
            previous = resume.lane_id
            if previous is not None:
                self.lanes.clear_default(user_id=user_id, resume_id=resume.id)
                self.lanes.touch(user_id=user_id, lane_id=previous)
            resume.lane_id = data.lane_id
            if data.lane_id is not None:
                self.lanes.touch(user_id=user_id, lane_id=data.lane_id)
        self.session.commit()
        return resume, artifact

    def set_archived(
        self, *, user_id: uuid.UUID, resume_id: uuid.UUID, archived: bool
    ) -> tuple[Resume, Artifact]:
        resume, artifact = self.resumes.get_with_artifact(user_id=user_id, id=resume_id)
        if archived and resume.status is ResumeStatus.ACTIVE:
            resume.status = ResumeStatus.ARCHIVED
            resume.archived_at = datetime.now(UTC)
            self.lanes.clear_default(user_id=user_id, resume_id=resume.id)
            if resume.lane_id is not None:
                self.lanes.touch(user_id=user_id, lane_id=resume.lane_id)
        elif not archived and resume.status is ResumeStatus.ARCHIVED:
            resume.status = ResumeStatus.ACTIVE
            resume.archived_at = None
            if resume.lane_id is not None:
                self.lanes.touch(user_id=user_id, lane_id=resume.lane_id)
        self.session.commit()
        return resume, artifact


class LaneService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.lanes = LaneRepository(session)

    def list(self, *, user_id: uuid.UUID) -> Sequence[ResumeLane]:
        return self.lanes.list_for_user(user_id=user_id)

    def create(self, *, user_id: uuid.UUID, data: LaneCreate) -> ResumeLane:
        self._require_free_name(user_id=user_id, name=data.name)
        lane = ResumeLane(
            user_id=user_id,
            name=data.name,
            description=data.description,
            emphasis_notes=data.emphasis_notes,
            target_role_labels=data.target_role_labels,
        )
        self.session.add(lane)
        return self._commit(lane)

    def patch(self, *, user_id: uuid.UUID, lane_id: uuid.UUID, data: LanePatch) -> ResumeLane:
        lane = self.lanes.get(user_id=user_id, id=lane_id)
        fields = data.model_fields_set
        if "name" in fields and data.name is not None and data.name != lane.name:
            if lane.status is LaneStatus.ACTIVE:
                self._require_free_name(user_id=user_id, name=data.name, exclude_id=lane.id)
            lane.name = data.name
        if "description" in fields and data.description is not None:
            lane.description = data.description
        if "emphasis_notes" in fields and data.emphasis_notes is not None:
            lane.emphasis_notes = data.emphasis_notes
        if "target_role_labels" in fields and data.target_role_labels is not None:
            lane.target_role_labels = data.target_role_labels
        if "default_resume_id" in fields:
            lane.default_resume_id = self._eligible_default(
                user_id=user_id, lane=lane, resume_id=data.default_resume_id
            )
        return self._commit(lane)

    def set_archived(self, *, user_id: uuid.UUID, lane_id: uuid.UUID, archived: bool) -> ResumeLane:
        lane = self.lanes.get(user_id=user_id, id=lane_id)
        target = LaneStatus.ARCHIVED if archived else LaneStatus.ACTIVE
        if lane.status is not target:
            if not archived:
                self._require_free_name(user_id=user_id, name=lane.name, exclude_id=lane.id)
            lane.status = target
        return self._commit(lane)

    def _eligible_default(
        self, *, user_id: uuid.UUID, lane: ResumeLane, resume_id: uuid.UUID | None
    ) -> uuid.UUID | None:
        if resume_id is None:
            return None
        resume = resolve_owned(self.session, Resume, user_id=user_id, id=resume_id)
        if resume.status is not ResumeStatus.ACTIVE or resume.lane_id != lane.id:
            raise ApiError(422, "invalid_default_resume")
        return resume.id

    def _require_free_name(
        self, *, user_id: uuid.UUID, name: str, exclude_id: uuid.UUID | None = None
    ) -> None:
        if self.lanes.active_name_taken(user_id=user_id, name=name, exclude_id=exclude_id):
            raise ApiError(409, "lane_name_taken")

    def _commit(self, lane: ResumeLane) -> ResumeLane:
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ApiError(409, "lane_name_taken") from exc
        self.session.refresh(lane)
        return lane
