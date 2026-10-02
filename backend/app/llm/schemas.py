import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class ManifestEntry(BaseModel):
    entity_type: str = Field(min_length=1, max_length=64)
    entity_id: uuid.UUID
    version: int = Field(ge=0)


class ContextManifest(BaseModel):
    schema_version: int = 1
    entries: list[ManifestEntry] = Field(default_factory=list)


class StructuredOutputRecord(BaseModel):
    schema_version: int = 1
    data: dict[str, Any]


class BudgetResponse(BaseModel):
    spent_usd: Decimal
    cap_usd: Decimal
    remaining_usd: Decimal
    resets_at: datetime
