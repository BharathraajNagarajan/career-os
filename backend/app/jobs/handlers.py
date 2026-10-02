from app.auth.deletion import (
    DELETE_ACCOUNT_JOB,
    DeleteAccountPayload,
    DeletionHooks,
    deletion_hooks,
    make_delete_account_handler,
)
from app.jobs.registry import JobRegistry


def register_job_handlers(registry: JobRegistry, hooks: DeletionHooks = deletion_hooks) -> None:
    registry.register(DELETE_ACCOUNT_JOB, DeleteAccountPayload, make_delete_account_handler(hooks))
