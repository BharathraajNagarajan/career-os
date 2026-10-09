import uuid
from datetime import datetime
from typing import Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.actions.schemas import ActionResponse
from app.contacts.emails import (
    MAX_EMAILS_PER_CONTACT,
    ContactEmail,
    ContactEmails,
    normalize_address,
)
from app.db.models import (
    Contact,
    ContactCompanyRelation,
    ContactOpportunityRole,
    ContactSource,
)
from app.interactions.schemas import InteractionResponse
from app.opportunities.schemas import clean_name, clean_optional_text, clean_url


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def clean_addresses(value: list[str]) -> list[str]:
    cleaned: dict[str, None] = {}
    for raw in value:
        address = normalize_address(raw)
        if address is None:
            raise ValueError("email address is not valid")
        cleaned.setdefault(address)
    return list(cleaned)


class ContactCreate(StrictModel):
    full_name: str = Field(max_length=200)
    emails: list[str] = Field(default_factory=list, max_length=MAX_EMAILS_PER_CONTACT)
    linkedin_url: str | None = None
    headline: str | None = Field(default=None, max_length=200)
    notes: str = Field(default="", max_length=5000)

    @field_validator("full_name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        return clean_name(value)

    @field_validator("emails")
    @classmethod
    def _clean_emails(cls, value: list[str]) -> list[str]:
        return clean_addresses(value)

    @field_validator("linkedin_url")
    @classmethod
    def _clean_linkedin(cls, value: str | None) -> str | None:
        return clean_url(value)

    @field_validator("headline")
    @classmethod
    def _clean_headline(cls, value: str | None) -> str | None:
        return clean_optional_text(value)


class ContactPatch(StrictModel):
    expected_updated_at: AwareDatetime
    full_name: str | None = Field(default=None, max_length=200)
    emails: list[str] | None = Field(default=None, max_length=MAX_EMAILS_PER_CONTACT)
    linkedin_url: str | None = None
    headline: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("full_name")
    @classmethod
    def _clean_name(cls, value: str | None) -> str | None:
        return None if value is None else clean_name(value)

    @field_validator("emails")
    @classmethod
    def _clean_emails(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else clean_addresses(value)

    @field_validator("linkedin_url")
    @classmethod
    def _clean_linkedin(cls, value: str | None) -> str | None:
        return clean_url(value)

    @field_validator("headline")
    @classmethod
    def _clean_headline(cls, value: str | None) -> str | None:
        return clean_optional_text(value)


class CompanyLinkRequest(StrictModel):
    relation: ContactCompanyRelation = ContactCompanyRelation.OTHER
    title: str | None = Field(default=None, max_length=200)
    is_current: bool = True

    @field_validator("title")
    @classmethod
    def _clean_title(cls, value: str | None) -> str | None:
        return clean_optional_text(value)


class OpportunityLinkRequest(StrictModel):
    role: ContactOpportunityRole


class MergeRequest(StrictModel):
    merged_id: uuid.UUID
    expected_survivor_updated_at: AwareDatetime
    expected_merged_updated_at: AwareDatetime


class EmailResponse(BaseModel):
    address: str
    source: str
    added_at: datetime

    @classmethod
    def build(cls, item: ContactEmail) -> Self:
        return cls(address=item.address, source=item.source.value, added_at=item.added_at)


class CompanyLinkResponse(BaseModel):
    company_id: uuid.UUID
    company_name: str
    relation: ContactCompanyRelation
    title: str | None
    is_current: bool


class OpportunityLinkResponse(BaseModel):
    opportunity_id: uuid.UUID
    opportunity_title: str | None
    company_name: str | None
    role: ContactOpportunityRole


class ContactSummary(BaseModel):
    id: uuid.UUID
    full_name: str
    emails: list[EmailResponse]
    headline: str | None
    source: ContactSource
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(cls, row: Contact) -> Self:
        return cls(
            id=row.id,
            full_name=row.full_name,
            emails=[
                EmailResponse.build(item) for item in ContactEmails.from_json(row.emails).items
            ],
            headline=row.headline,
            source=row.source,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class ContactDetail(ContactSummary):
    linkedin_url: str | None
    notes: str
    companies: list[CompanyLinkResponse]
    opportunities: list[OpportunityLinkResponse]
    interactions: list[InteractionResponse]
    actions: list[ActionResponse]
