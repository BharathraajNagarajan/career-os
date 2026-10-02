import uuid
from collections.abc import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import UserOwned


class NotFound(Exception):
    pass


def require_user_id(user_id: uuid.UUID) -> uuid.UUID:
    if not isinstance(user_id, uuid.UUID):
        raise TypeError("user_id must be a UUID")
    return user_id


def resolve_owned[O: UserOwned](
    session: Session, model: type[O], *, user_id: uuid.UUID, id: uuid.UUID
) -> O:
    row = session.scalars(
        select(model).where(model.user_id == require_user_id(user_id), model.id == id)
    ).one_or_none()
    if row is None:
        raise NotFound(model.__name__)
    return row


def resolve_owned_many[O: UserOwned](
    session: Session, model: type[O], *, user_id: uuid.UUID, ids: Iterable[uuid.UUID]
) -> Sequence[O]:
    wanted = list(dict.fromkeys(ids))
    if not wanted:
        return []
    rows = session.scalars(
        select(model).where(model.user_id == require_user_id(user_id), model.id.in_(wanted))
    ).all()
    by_id = {row.id: row for row in rows}
    return [by_id[id] for id in wanted if id in by_id]


class UserScopedRepository[O: UserOwned]:
    model: type[O]

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, *, user_id: uuid.UUID, id: uuid.UUID) -> O:
        return resolve_owned(self.session, self.model, user_id=user_id, id=id)

    def get_many(self, *, user_id: uuid.UUID, ids: Iterable[uuid.UUID]) -> Sequence[O]:
        return resolve_owned_many(self.session, self.model, user_id=user_id, ids=ids)
