import uuid

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.db.models import Profile
from app.db.tenancy import UserScopedRepository, require_user_id
from app.profile.schemas import (
    CommunicationPreferences,
    CommunicationPreferencesPayload,
    ProfileResponse,
    ProfileUpdate,
    TargetRolesPayload,
    WorkAuthorizationPayload,
)


class ProfileRepository(UserScopedRepository[Profile]):
    model = Profile

    def get_or_create(self, *, user_id: uuid.UUID) -> Profile:
        require_user_id(user_id)
        self.session.execute(
            insert(Profile)
            .values(
                id=new_id(),
                user_id=user_id,
                work_authorization=WorkAuthorizationPayload().model_dump(mode="json"),
                target_roles=TargetRolesPayload().model_dump(mode="json"),
                communication_preferences=CommunicationPreferencesPayload().model_dump(mode="json"),
            )
            .on_conflict_do_nothing(index_elements=[Profile.user_id])
        )
        return self.session.scalars(select(Profile).where(Profile.user_id == user_id)).one()


def to_response(profile: Profile) -> ProfileResponse:
    preferences = CommunicationPreferencesPayload.model_validate(profile.communication_preferences)
    return ProfileResponse(
        headline=profile.headline,
        summary=profile.summary,
        current_location=profile.current_location,
        relocation_preference=profile.relocation_preference,
        remote_preference=profile.remote_preference,
        work_authorization=WorkAuthorizationPayload.model_validate(
            profile.work_authorization
        ).entries,
        target_roles=TargetRolesPayload.model_validate(profile.target_roles).roles,
        communication_preferences=CommunicationPreferences(
            **preferences.model_dump(exclude={"schema_version"})
        ),
        constraints_updated_at=profile.constraints_updated_at,
        updated_at=profile.updated_at,
    )


class ProfileService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.profiles = ProfileRepository(session)

    def get(self, *, user_id: uuid.UUID) -> Profile:
        profile = self.profiles.get_or_create(user_id=user_id)
        self.session.commit()
        return profile

    def replace(self, *, user_id: uuid.UUID, data: ProfileUpdate) -> Profile:
        profile = self.profiles.get_or_create(user_id=user_id)
        work_authorization = WorkAuthorizationPayload(entries=data.work_authorization).model_dump(
            mode="json"
        )
        constraints_changed = (
            profile.current_location != data.current_location
            or profile.relocation_preference != data.relocation_preference
            or profile.remote_preference != data.remote_preference
            or profile.work_authorization != work_authorization
        )
        profile.headline = data.headline
        profile.summary = data.summary
        profile.current_location = data.current_location
        profile.relocation_preference = data.relocation_preference
        profile.remote_preference = data.remote_preference
        profile.work_authorization = work_authorization
        profile.target_roles = TargetRolesPayload(roles=data.target_roles).model_dump(mode="json")
        profile.communication_preferences = CommunicationPreferencesPayload(
            **data.communication_preferences.model_dump()
        ).model_dump(mode="json")
        if constraints_changed:
            self.session.flush()
            self.session.execute(
                update(Profile)
                .where(Profile.user_id == user_id, Profile.id == profile.id)
                .values(constraints_updated_at=func.now())
            )
        self.session.commit()
        self.session.refresh(profile)
        return profile
