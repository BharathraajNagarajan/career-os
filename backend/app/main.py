from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, sessionmaker

from app import __version__
from app.artifacts.storage import FilesystemStorage, StorageAdapter
from app.auth.oidc import IdentityProvider
from app.auth.router import router as auth_router
from app.config import Settings, get_settings
from app.core.db import create_db_engine
from app.core.db import session_factory as make_session_factory
from app.core.errors import install_error_handlers
from app.core.health import router as health_router
from app.core.logging import configure_logging, get_logger
from app.core.middleware import REQUEST_ID_HEADER, RequestContextMiddleware
from app.llm.router import router as llm_router
from app.profile.router import router as profile_router
from app.resumes.router import router as resumes_router
from app.review.handlers import ReviewHandlerRegistry
from app.review.router import router as review_router


def create_app(
    settings: Settings | None = None,
    *,
    session_factory: sessionmaker[Session] | None = None,
    identity_provider: IdentityProvider | None = None,
    storage: StorageAdapter | None = None,
    review_registry: ReviewHandlerRegistry | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)
    engine = None if session_factory else create_db_engine(settings.database_url)
    if session_factory is None and engine is not None:
        session_factory = make_session_factory(engine)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if engine is not None:
            engine.dispose()

    app = FastAPI(
        lifespan=lifespan,
        title="Career OS API",
        version=__version__,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    if settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Content-Type", "X-CSRF-Token", REQUEST_ID_HEADER],
            expose_headers=[REQUEST_ID_HEADER],
        )
    app.add_middleware(RequestContextMiddleware)
    app.state.session_factory = session_factory
    app.state.identity_provider = identity_provider
    app.state.settings = settings
    app.state.review_registry = review_registry or ReviewHandlerRegistry()
    app.state.storage = storage or FilesystemStorage(settings.artifact_storage_dir)
    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(profile_router)
    app.include_router(resumes_router)
    app.include_router(llm_router)
    app.include_router(review_router)

    get_logger(__name__).info(
        "api_configured", environment=settings.environment.value, version=__version__
    )
    return app
