from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict

Upcaster = Callable[[dict[str, Any]], dict[str, Any]]


class EventPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int


class UnknownEventType(Exception):
    pass


@dataclass(frozen=True)
class PayloadSchema:
    model: type[EventPayload]
    version: int
    upcasters: Mapping[int, Upcaster] = field(default_factory=dict)


class PayloadRegistry:
    def __init__(self) -> None:
        self._schemas: dict[str, PayloadSchema] = {}

    def register(
        self,
        event_type: str,
        model: type[EventPayload],
        *,
        version: int,
        upcasters: Mapping[int, Upcaster] | None = None,
    ) -> None:
        missing = set(range(1, version)) - set(upcasters or {})
        if event_type in self._schemas or missing:
            raise ValueError(event_type)
        self._schemas[event_type] = PayloadSchema(model, version, dict(upcasters or {}))

    def dump(self, event_type: str, payload: EventPayload) -> dict[str, Any]:
        schema = self._schema(event_type)
        if not isinstance(payload, schema.model) or payload.schema_version != schema.version:
            raise ValueError(event_type)
        return payload.model_dump(mode="json")

    def load(self, event_type: str, raw: Mapping[str, Any]) -> EventPayload:
        schema = self._schema(event_type)
        data = dict(raw)
        while data["schema_version"] < schema.version:
            version = data["schema_version"]
            data = {**schema.upcasters[version](data), "schema_version": version + 1}
        return schema.model.model_validate(data)

    def _schema(self, event_type: str) -> PayloadSchema:
        if event_type not in self._schemas:
            raise UnknownEventType(event_type)
        return self._schemas[event_type]


payload_registry = PayloadRegistry()
