import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class JobContext:
    session: Session
    job_id: uuid.UUID
    user_id: uuid.UUID | None
    correlation_id: uuid.UUID | None

    def require_user_id(self) -> uuid.UUID:
        if self.user_id is None:
            raise PermissionError("job has no user_id")
        return self.user_id


@dataclass(frozen=True)
class JobHandler[P: BaseModel]:
    payload_model: type[P]
    handle: Callable[[JobContext, P], None]


class JobRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler[Any]] = {}

    def register[P: BaseModel](
        self, kind: str, payload_model: type[P], handle: Callable[[JobContext, P], None]
    ) -> None:
        if kind in self._handlers:
            raise ValueError(kind)
        self._handlers[kind] = JobHandler(payload_model, handle)

    def get(self, kind: str) -> JobHandler[Any] | None:
        return self._handlers.get(kind)


job_registry = JobRegistry()
