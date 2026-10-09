import re
from datetime import datetime
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, model_validator

EMAILS_SCHEMA_VERSION = 1
MAX_EMAILS_PER_CONTACT = 10
MAX_ADDRESS_CHARS = 254
DOMAIN_LABEL = r"[a-z0-9]([a-z0-9-]*[a-z0-9])?"
ADDRESS_PATTERN = re.compile(rf"^[^@\s<>()\[\],;:\\\"]+@{DOMAIN_LABEL}(\.{DOMAIN_LABEL})+$")


class EmailSource(StrEnum):
    MANUAL = "manual"
    GMAIL = "gmail"
    PROVIDER = "provider"


class ContactEmail(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    address: str
    source: EmailSource
    added_at: datetime


class ContactEmails(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = EMAILS_SCHEMA_VERSION
    items: tuple[ContactEmail, ...] = ()

    @model_validator(mode="after")
    def _unique_addresses(self) -> Self:
        addresses = [item.address for item in self.items]
        if len(set(addresses)) != len(addresses) or len(addresses) > MAX_EMAILS_PER_CONTACT:
            raise ValueError("emails")
        return self

    @property
    def addresses(self) -> list[str]:
        return [item.address for item in self.items]

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Self:
        return cls.model_validate(raw)


def normalize_address(raw: str) -> str | None:
    address = raw.strip().lower()
    if len(address) > MAX_ADDRESS_CHARS or not ADDRESS_PATTERN.match(address):
        return None
    return address
