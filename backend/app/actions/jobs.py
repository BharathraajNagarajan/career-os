import uuid

from pydantic import BaseModel

WAKE_ACTION_JOB = "wake_action"


class WakeActionPayload(BaseModel):
    action_id: uuid.UUID
    state_version: int


def wake_unique_key(action_id: uuid.UUID, state_version: int) -> str:
    return f"{WAKE_ACTION_JOB}:{action_id}:{state_version}"
