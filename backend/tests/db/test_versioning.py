import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, Text, Uuid, insert, select
from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.db.versioning import ConcurrencyConflict, update_versioned

pytestmark = pytest.mark.db

items = Table(
    "versioned_items",
    MetaData(),
    Column("id", Uuid, primary_key=True),
    Column("user_id", Uuid, nullable=False),
    Column("title", Text, nullable=False),
    Column("state_version", Integer, nullable=False, server_default="1"),
    prefixes=["TEMPORARY"],
)


@pytest.fixture
def item(session: Session) -> Iterator[tuple[uuid.UUID, uuid.UUID]]:
    items.create(session.connection())
    item_id, user_id = new_id(), new_id()
    session.execute(insert(items).values(id=item_id, user_id=user_id, title="first"))
    yield item_id, user_id
    session.rollback()


def test_update_with_expected_version_increments_it(
    session: Session, item: tuple[uuid.UUID, uuid.UUID]
) -> None:
    item_id, user_id = item

    version = update_versioned(
        session, items, user_id=user_id, id=item_id, expected_version=1, values={"title": "second"}
    )

    assert version == 2
    assert session.execute(select(items.c.title)).scalar_one() == "second"


def test_stale_version_raises_conflict(session: Session, item: tuple[uuid.UUID, uuid.UUID]) -> None:
    item_id, user_id = item
    update_versioned(
        session, items, user_id=user_id, id=item_id, expected_version=1, values={"title": "a"}
    )

    with pytest.raises(ConcurrencyConflict):
        update_versioned(
            session, items, user_id=user_id, id=item_id, expected_version=1, values={"title": "b"}
        )
    assert session.execute(select(items.c.title)).scalar_one() == "a"


def test_other_users_row_is_never_updated(
    session: Session, item: tuple[uuid.UUID, uuid.UUID]
) -> None:
    item_id, _ = item

    with pytest.raises(ConcurrencyConflict):
        update_versioned(
            session, items, user_id=new_id(), id=item_id, expected_version=1, values={"title": "x"}
        )
