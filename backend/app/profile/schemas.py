import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.db.models import RelocationPreference, RemotePreference

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]
AvoidItem = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
_COUNTRY = re.compile(r"^[A-Z]{2}$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkAuthorizationEntry(StrictModel):
    country: str
    status: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    sponsorship_needed: bool | None = None

    @field_validator("country")
    @classmethod
    def country_code(cls, value: str) -> str:
        code = value.strip().upper()
        if not _COUNTRY.fullmatch(code):
            raise ValueError("country must be an ISO 3166-1 alpha-2 code")
        return code


class TargetRole(StrictModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    priority: Literal["high", "normal", "low"] = "normal"
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] = ""


class CommunicationPreferences(StrictModel):
    tone: ShortText = ""
    length: ShortText = ""
    sign_off: ShortText = ""
    avoid: list[AvoidItem] = Field(default_factory=list, max_length=30)


class WorkAuthorizationPayload(StrictModel):
    schema_version: Literal[1] = 1
    entries: list[WorkAuthorizationEntry] = Field(default_factory=list, max_length=20)


class TargetRolesPayload(StrictModel):
    schema_version: Literal[1] = 1
    roles: list[TargetRole] = Field(default_factory=list, max_length=20)


class CommunicationPreferencesPayload(CommunicationPreferences):
    schema_version: Literal[1] = 1


class ProfileUpdate(StrictModel):
    headline: ShortText | None = None
    summary: LongText | None = None
    current_location: ShortText | None = None
    relocation_preference: RelocationPreference = RelocationPreference.UNSPECIFIED
    remote_preference: RemotePreference = RemotePreference.NO_PREFERENCE
    work_authorization: list[WorkAuthorizationEntry] = Field(default_factory=list, max_length=20)
    target_roles: list[TargetRole] = Field(default_factory=list, max_length=20)
    communication_preferences: CommunicationPreferences = Field(
        default_factory=CommunicationPreferences
    )

    @field_validator("headline", "summary", "current_location", mode="after")
    @classmethod
    def blank_is_unset(cls, value: str | None) -> str | None:
        return value or None


class ProfileResponse(BaseModel):
    headline: str | None
    summary: str | None
    current_location: str | None
    relocation_preference: RelocationPreference
    remote_preference: RemotePreference
    work_authorization: list[WorkAuthorizationEntry]
    target_roles: list[TargetRole]
    communication_preferences: CommunicationPreferences
    constraints_updated_at: datetime
    updated_at: datetime
