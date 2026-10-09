from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.applications.events import ApplicationNoted, noted_v1_to_v2
from app.contacts.emails import (
    MAX_EMAILS_PER_CONTACT,
    ContactEmail,
    ContactEmails,
    EmailSource,
    normalize_address,
)
from app.events.payloads import payload_registry
from app.state_machines.application import ApplicationEventType

NOW = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Alex.Example@Example.TEST ", "alex.example@example.test"),
        ("alex+tag@sub.example.test", "alex+tag@sub.example.test"),
        ("not-an-email", None),
        ("alex@localhost", None),
        ("a b@example.test", None),
        ("alex@@example.test", None),
        ("<alex@example.test>", None),
        ("alex@-example.test", None),
        (f"{'a' * 250}@example.test", None),
    ],
)
def test_addresses_are_trimmed_lowercased_and_validated(raw: str, expected: str | None) -> None:
    assert normalize_address(raw) == expected


def item(address: str, source: EmailSource = EmailSource.MANUAL) -> ContactEmail:
    return ContactEmail(address=address, source=source, added_at=NOW)


def test_emails_round_trip_with_a_schema_version_and_per_address_source() -> None:
    emails = ContactEmails(
        items=(item("a@example.test"), item("b@example.test", EmailSource.GMAIL))
    )

    raw = emails.to_json()

    assert raw["schema_version"] == 1
    assert [(entry["address"], entry["source"]) for entry in raw["items"]] == [
        ("a@example.test", "manual"),
        ("b@example.test", "gmail"),
    ]
    assert ContactEmails.from_json(raw) == emails


def test_duplicate_addresses_and_unknown_sources_are_refused() -> None:
    with pytest.raises(ValidationError):
        ContactEmails(items=(item("a@example.test"), item("a@example.test")))
    with pytest.raises(ValidationError):
        ContactEmails.from_json(
            {
                "schema_version": 1,
                "items": [
                    {"address": "a@example.test", "source": "import", "added_at": NOW.isoformat()}
                ],
            }
        )
    with pytest.raises(ValidationError):
        ContactEmails(
            items=tuple(
                item(f"a{index}@example.test") for index in range(MAX_EMAILS_PER_CONTACT + 1)
            )
        )


@pytest.mark.parametrize(
    "event_type",
    [
        event
        for event in ApplicationEventType
        if event.value not in {"APPLICATION_SUBMITTED", "EVENT_VOIDED"}
    ],
)
def test_every_note_payload_upcasts_from_version_1(event_type: ApplicationEventType) -> None:
    legacy = {
        "schema_version": 1,
        "application_id": "00000000-0000-4000-8000-000000000001",
        "note": "Before interactions",
    }

    loaded = payload_registry.load(event_type.value, legacy)

    assert isinstance(loaded, ApplicationNoted)
    assert (loaded.schema_version, loaded.interaction_id, loaded.note) == (
        2,
        None,
        "Before interactions",
    )
    assert noted_v1_to_v2(legacy)["interaction_id"] is None


def test_a_version_2_note_payload_keeps_its_interaction_id() -> None:
    raw = {
        "schema_version": 2,
        "application_id": "00000000-0000-4000-8000-000000000001",
        "note": None,
        "interaction_id": "00000000-0000-4000-8000-000000000002",
    }

    loaded = payload_registry.load("OUTREACH_SENT", raw)

    assert isinstance(loaded, ApplicationNoted)
    assert str(loaded.interaction_id) == raw["interaction_id"]
