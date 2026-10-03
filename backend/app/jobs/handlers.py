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
from app.llm.gateway import ModelGateway
from app.opportunities.extraction import make_extract_jd_handler
from app.opportunities.jobs import EXTRACT_JD_JOB, ExtractJdPayload
from app.resumes.parse_job import PARSE_RESUME_JOB, ParseResumePayload, make_parse_resume_handler


def register_job_handlers(
    registry: JobRegistry,
    hooks: DeletionHooks = deletion_hooks,
    *,
    storage: StorageAdapter,
    settings: Settings,
    gateway: ModelGateway | None = None,
) -> None:
    hooks.register("artifact_storage", make_storage_deletion_hook(storage))
    registry.register(DELETE_ACCOUNT_JOB, DeleteAccountPayload, make_delete_account_handler(hooks))
    registry.register(
        PARSE_RESUME_JOB, ParseResumePayload, make_parse_resume_handler(storage, settings)
    )
    if gateway is not None:
        registry.register(
            EXTRACT_JD_JOB, ExtractJdPayload, make_extract_jd_handler(gateway, settings)
        )
