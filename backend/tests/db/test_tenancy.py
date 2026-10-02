import pytest
from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.db.models import AggregateType, DomainEvent
from app.db.tenancy import NotFound, resolve_owned, resolve_owned_many
from app.events.repository import DomainEventRepository
from tests.db.factories import make_event, make_user

pytestmark = pytest.mark.db


def test_foreign_and_missing_ids_are_both_not_found(session: Session) -> None:
    owner = make_user(session)
    other = make_user(session)
    foreign = make_event(session, other.id)
    session.commit()

    with pytest.raises(NotFound) as foreign_error:
        resolve_owned(session, DomainEvent, user_id=owner.id, id=foreign.id)
    with pytest.raises(NotFound) as missing_error:
        resolve_owned(session, DomainEvent, user_id=owner.id, id=new_id())

    assert str(foreign_error.value) == str(missing_error.value)


def test_resolve_owned_returns_own_row(session: Session) -> None:
    user = make_user(session)
    event = make_event(session, user.id)
    session.commit()

    assert resolve_owned(session, DomainEvent, user_id=user.id, id=event.id) is event


def test_resolve_owned_many_drops_foreign_and_missing_ids(session: Session) -> None:
    owner = make_user(session)
    other = make_user(session)
    first = make_event(session, owner.id)
    second = make_event(session, owner.id)
    foreign = make_event(session, other.id)
    session.commit()

    resolved = resolve_owned_many(
        session,
        DomainEvent,
        user_id=owner.id,
        ids=[second.id, foreign.id, new_id(), first.id, second.id],
    )

    assert [event.id for event in resolved] == [second.id, first.id]


def test_repository_lists_only_the_users_events_for_an_aggregate(session: Session) -> None:
    owner = make_user(session)
    other = make_user(session)
    event = make_event(session, owner.id)
    session.commit()
    repository = DomainEventRepository(session)

    mine = repository.list_for_aggregate(
        user_id=owner.id, aggregate_type=AggregateType.OPPORTUNITY, aggregate_id=event.aggregate_id
    )
    theirs = repository.list_for_aggregate(
        user_id=other.id, aggregate_type=AggregateType.OPPORTUNITY, aggregate_id=event.aggregate_id
    )

    assert [row.id for row in mine] == [event.id]
    assert theirs == []


def test_append_does_not_commit(session: Session) -> None:
    user = make_user(session)
    session.commit()
    event = make_event(session, user.id)
    session.rollback()

    with pytest.raises(NotFound):
        DomainEventRepository(session).get(user_id=user.id, id=event.id)
