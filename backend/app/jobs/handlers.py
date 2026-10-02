from app.artifacts.deletion import make_storage_deletion_hook
from app.artifacts.storage import StorageAdapter
from app.auth.deletion import (
    DELETE_ACCOUNT_JOB,
    DeleteAccountPayload,
    DeletionHooks,
    deletion_hooks,
    make_delete_account_handler,
)
from app.config import Settings
from app.jobs.registry import JobRegistry
from app.resumes.parse_job import PARSE_RESUME_JOB, ParseResumePayload, make_parse_resume_handler


def register_job_handlers(
    registry: JobRegistry,
    hooks: DeletionHooks = deletion_hooks,
    *,
    storage: StorageAdapter,
    settings: Settings,
) -> None:
    hooks.register("artifact_storage", make_storage_deletion_hook(storage))
    registry.register(DELETE_ACCOUNT_JOB, DeleteAccountPayload, make_delete_account_handler(hooks))
    registry.register(
        PARSE_RESUME_JOB, ParseResumePayload, make_parse_resume_handler(storage, settings)
    )
