import uuid

from pydantic import BaseModel

EXTRACT_JD_JOB = "extract_jd"


class ExtractJdPayload(BaseModel):
    opportunity_id: uuid.UUID


def extract_unique_key(opportunity_id: uuid.UUID) -> str:
    return f"{EXTRACT_JD_JOB}:{opportunity_id}"
