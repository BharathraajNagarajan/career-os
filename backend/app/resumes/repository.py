import uuid
from collections.abc import Sequence

from sqlalchemy import Select, and_, func, select, update

from app.db.models import Artifact, ArtifactKind, LaneStatus, Resume, ResumeLane
from app.db.tenancy import NotFound, UserScopedRepository, require_user_id


class ArtifactRepository(UserScopedRepository[Artifact]):
    model = Artifact

    def find_by_hash(
        self, *, user_id: uuid.UUID, sha256: bytes, kind: ArtifactKind
    ) -> Artifact | None:
        return self.session.scalars(
            select(Artifact).where(
                Artifact.user_id == require_user_id(user_id),
                Artifact.sha256 == sha256,
                Artifact.kind == kind,
            )
        ).one_or_none()


class ResumeRepository(UserScopedRepository[Resume]):
    model = Resume

    def _with_artifact(self, user_id: uuid.UUID) -> Select[Resume, Artifact]:
        return (
            select(Resume, Artifact)
            .join(
                Artifact,
                and_(Artifact.user_id == Resume.user_id, Artifact.id == Resume.artifact_id),
            )
            .where(Resume.user_id == require_user_id(user_id))
        )

    def list_with_artifacts(self, *, user_id: uuid.UUID) -> Sequence[tuple[Resume, Artifact]]:
        statement = self._with_artifact(user_id).order_by(Resume.created_at.desc(), Resume.id)
        return self.session.execute(statement).tuples().all()

    def get_with_artifact(self, *, user_id: uuid.UUID, id: uuid.UUID) -> tuple[Resume, Artifact]:
        row = (
            self.session.execute(self._with_artifact(user_id).where(Resume.id == id))
            .tuples()
            .one_or_none()
        )
        if row is None:
            raise NotFound("Resume")
        return row

    def find_by_artifact(self, *, user_id: uuid.UUID, artifact_id: uuid.UUID) -> Resume | None:
        return self.session.scalars(
            select(Resume).where(
                Resume.user_id == require_user_id(user_id), Resume.artifact_id == artifact_id
            )
        ).one_or_none()


class LaneRepository(UserScopedRepository[ResumeLane]):
    model = ResumeLane

    def list_for_user(self, *, user_id: uuid.UUID) -> Sequence[ResumeLane]:
        return self.session.scalars(
            select(ResumeLane)
            .where(ResumeLane.user_id == require_user_id(user_id))
            .order_by(ResumeLane.created_at, ResumeLane.id)
        ).all()

    def active_name_taken(
        self, *, user_id: uuid.UUID, name: str, exclude_id: uuid.UUID | None = None
    ) -> bool:
        statement = select(ResumeLane.id).where(
            ResumeLane.user_id == require_user_id(user_id),
            ResumeLane.status == LaneStatus.ACTIVE,
            func.lower(ResumeLane.name) == name.lower(),
        )
        if exclude_id is not None:
            statement = statement.where(ResumeLane.id != exclude_id)
        return self.session.scalars(statement.limit(1)).first() is not None

    def touch(self, *, user_id: uuid.UUID, lane_id: uuid.UUID) -> None:
        self.session.execute(
            update(ResumeLane)
            .where(ResumeLane.user_id == require_user_id(user_id), ResumeLane.id == lane_id)
            .values(updated_at=func.now())
            .execution_options(synchronize_session=False)
        )

    def clear_default(self, *, user_id: uuid.UUID, resume_id: uuid.UUID) -> None:
        self.session.execute(
            update(ResumeLane)
            .where(
                ResumeLane.user_id == require_user_id(user_id),
                ResumeLane.default_resume_id == resume_id,
            )
            .values(default_resume_id=None, updated_at=func.now())
            .execution_options(synchronize_session=False)
        )
