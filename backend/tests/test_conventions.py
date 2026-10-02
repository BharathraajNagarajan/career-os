import uuid
from typing import cast

import pytest
from sqlalchemy import Table, UniqueConstraint
from sqlalchemy.orm import Session

from app.db.base import Base, UserOwned
from app.db.models import AggregateType, DomainEvent
from app.db.tenancy import require_user_id
from app.events.repository import DomainEventRepository


def owned_tables() -> list[Table]:
    return [
        cast(Table, mapper.local_table)
        for mapper in Base.registry.mappers
        if issubclass(mapper.class_, UserOwned)
    ]


def test_every_user_owned_table_has_unique_user_id_id() -> None:
    assert DomainEvent.__table__ in owned_tables()
    for table in owned_tables():
        uniques = {
            tuple(column.name for column in constraint.columns)
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        assert ("user_id", "id") in uniques, table.name


def test_every_constraint_and_index_is_named() -> None:
    for table in Base.metadata.tables.values():
        names = [item.name for item in table.constraints] + [item.name for item in table.indexes]
        assert all(isinstance(name, str) for name in names), table.name


def test_require_user_id_rejects_non_uuid() -> None:
    with pytest.raises(TypeError):
        require_user_id(cast(uuid.UUID, None))
    with pytest.raises(TypeError):
        require_user_id(cast(uuid.UUID, str(uuid.uuid4())))


def test_repository_methods_require_user_id_keyword() -> None:
    repository = DomainEventRepository(cast(Session, None))

    with pytest.raises(TypeError):
        repository.get(id=uuid.uuid4())  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        repository.get(uuid.uuid4(), uuid.uuid4())  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        repository.list_for_aggregate(
            user_id=cast(uuid.UUID, None),
            aggregate_type=AggregateType.OPPORTUNITY,
            aggregate_id=uuid.uuid4(),
        )
