import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import Table, update
from sqlalchemy.orm import Session

from app.db.tenancy import require_user_id


class ConcurrencyConflict(Exception):
    pass


def update_versioned(
    session: Session,
    table: Table,
    *,
    user_id: uuid.UUID,
    id: uuid.UUID,
    expected_version: int,
    values: Mapping[str, Any],
) -> int:
    statement = (
        update(table)
        .where(
            table.c.id == id,
            table.c.user_id == require_user_id(user_id),
            table.c.state_version == expected_version,
        )
        .values(**values, state_version=table.c.state_version + 1)
        .returning(table.c.state_version)
    )
    new_version = session.execute(statement).scalar_one_or_none()
    if new_version is None:
        raise ConcurrencyConflict(table.name)
    return int(new_version)
