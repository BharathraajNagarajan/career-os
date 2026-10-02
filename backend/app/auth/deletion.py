import uuid
from collections.abc import Callable

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import User, UserStatus
from app.jobs.registry import JobContext

log = get_logger(__name__)

DELETE_ACCOUNT_JOB = "delete_account"

DeletionHook = Callable[[Session, uuid.UUID], None]


class DeletionHooks:
    def __init__(self) -> None:
        self._hooks: list[tuple[str, DeletionHook]] = []

    def register(self, name: str, hook: DeletionHook) -> None:
        if any(existing == name for existing, _ in self._hooks):
            raise ValueError(name)
        self._hooks.append((name, hook))

    def run(self, session: Session, user_id: uuid.UUID) -> None:
        for _, hook in self._hooks:
            hook(session, user_id)


deletion_hooks = DeletionHooks()


class DeleteAccountPayload(BaseModel):
    user_id: uuid.UUID


def delete_account_unique_key(user_id: uuid.UUID) -> str:
    return f"{DELETE_ACCOUNT_JOB}:{user_id}"


def make_delete_account_handler(
    hooks: DeletionHooks,
) -> Callable[[JobContext, DeleteAccountPayload], None]:
    def handle(context: JobContext, payload: DeleteAccountPayload) -> None:
        session = context.session
        user = session.get(User, payload.user_id)
        if user is None:
            log.info("account_already_deleted")
            return
        if user.status != UserStatus.DELETION_REQUESTED:
            raise PermissionError("user_not_pending_deletion")
        hooks.run(session, payload.user_id)
        deleted: bool = session.execute(
            select(func.public.delete_user_account(payload.user_id))
        ).scalar_one()
        log.info("account_deleted", outcome="deleted" if deleted else "not_deleted")

    return handle
