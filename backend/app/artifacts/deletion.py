import uuid

from sqlalchemy.orm import Session

from app.artifacts.storage import StorageAdapter, user_prefix
from app.auth.deletion import DeletionHook
from app.core.logging import get_logger

log = get_logger(__name__)


def make_storage_deletion_hook(storage: StorageAdapter) -> DeletionHook:
    def delete_user_objects(_: Session, user_id: uuid.UUID) -> None:
        storage.delete_prefix(user_prefix(user_id))
        log.info("user_objects_deleted")

    return delete_user_objects
