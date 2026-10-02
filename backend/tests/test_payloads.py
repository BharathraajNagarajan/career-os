from typing import Any

import pytest

from app.events.payloads import EventPayload, PayloadRegistry, UnknownEventType


class RenamedPayload(EventPayload):
    schema_version: int = 3
    title: str
    weight: int


def v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    return {"title": data["name"]}


def v2_to_v3(data: dict[str, Any]) -> dict[str, Any]:
    return {**data, "weight": 1}


@pytest.fixture
def registry() -> PayloadRegistry:
    registry = PayloadRegistry()
    registry.register("renamed", RenamedPayload, version=3, upcasters={1: v1_to_v2, 2: v2_to_v3})
    return registry


def test_load_upcasts_every_historical_version(registry: PayloadRegistry) -> None:
    from_v1 = registry.load("renamed", {"schema_version": 1, "name": "a"})
    from_v2 = registry.load("renamed", {"schema_version": 2, "title": "a"})
    current = registry.load("renamed", {"schema_version": 3, "title": "a", "weight": 1})

    assert from_v1 == from_v2 == current == RenamedPayload(title="a", weight=1)


def test_dump_includes_schema_version(registry: PayloadRegistry) -> None:
    assert registry.dump("renamed", RenamedPayload(title="a", weight=2)) == {
        "schema_version": 3,
        "title": "a",
        "weight": 2,
    }


def test_dump_rejects_stale_schema_version(registry: PayloadRegistry) -> None:
    with pytest.raises(ValueError, match="renamed"):
        registry.dump("renamed", RenamedPayload(schema_version=2, title="a", weight=2))


def test_unknown_event_type_is_rejected(registry: PayloadRegistry) -> None:
    with pytest.raises(UnknownEventType):
        registry.load("missing", {"schema_version": 1})


def test_registration_requires_an_upcaster_for_every_old_version() -> None:
    with pytest.raises(ValueError, match="renamed"):
        PayloadRegistry().register("renamed", RenamedPayload, version=3, upcasters={2: v2_to_v3})
