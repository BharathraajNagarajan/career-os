import uuid

from pydantic import Field

from app.events.payloads import EventPayload, payload_registry

CONTACT_CREATED = "CONTACT_CREATED"
CONTACT_EDITED = "CONTACT_EDITED"
CONTACT_MERGED = "CONTACT_MERGED"
CONTACT_LINKED = "CONTACT_LINKED"
CONTACT_UNLINKED = "CONTACT_UNLINKED"


class ContactCreated(EventPayload):
    schema_version: int = 1
    contact_id: uuid.UUID
    source: str
    email_count: int


class ContactEdited(EventPayload):
    schema_version: int = 1
    contact_id: uuid.UUID
    fields: list[str] = Field(max_length=10)


class ContactMerged(EventPayload):
    schema_version: int = 1
    survivor_id: uuid.UUID
    merged_id: uuid.UUID
    moved_interactions: int
    moved_actions: int
    moved_links: int


class ContactLinkChanged(EventPayload):
    schema_version: int = 1
    contact_id: uuid.UUID
    target_type: str
    target_id: uuid.UUID
    role: str


payload_registry.register(CONTACT_CREATED, ContactCreated, version=1)
payload_registry.register(CONTACT_EDITED, ContactEdited, version=1)
payload_registry.register(CONTACT_MERGED, ContactMerged, version=1)
payload_registry.register(CONTACT_LINKED, ContactLinkChanged, version=1)
payload_registry.register(CONTACT_UNLINKED, ContactLinkChanged, version=1)
