import uuid

import uuid6


def new_id() -> uuid.UUID:
    return uuid.UUID(bytes=uuid6.uuid7().bytes)
