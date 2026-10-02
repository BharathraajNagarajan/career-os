import os
import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from app.config import AuthSettings, Environment, Settings, get_auth_settings
from app.core.db import database_url, session_factory
from app.db.bootstrap import APP_ROLE, bootstrap
from app.main import create_app
from tests.auth.fake_idp import FAKE_CLIENT_ID, FakeIdentityProvider
from tests.db.review_helpers import recording_registry

BACKEND = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Database:
    owner_url: URL
    app_url: URL
    owner: Engine
    app: Engine


def alembic_config() -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.attributes["configure_logger"] = False
    return config


def secret(url: URL) -> SecretStr:
    return SecretStr(url.render_as_string(hide_password=False))


@pytest.fixture(scope="session")
def database() -> Iterator[Database]:
    admin_url = database_url(SecretStr(os.environ["TEST_ADMIN_DATABASE_URL"]))
    app_password = SecretStr(os.environ["APP_DB_PASSWORD"])
    name = f"career_os_test_{secrets.token_hex(4)}"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    owner_url = admin_url.set(database=name)
    app_url = owner_url.set(username=APP_ROLE, password=app_password.get_secret_value())
    try:
        bootstrap(secret(owner_url), app_password)
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("MIGRATION_DATABASE_URL", owner_url.render_as_string(hide_password=False))
            command.upgrade(alembic_config(), "head")
        owner = create_engine(owner_url, hide_parameters=True)
        app = create_engine(app_url, hide_parameters=True)
        yield Database(owner_url, app_url, owner, app)
        owner.dispose()
        app.dispose()
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def app_sessions(database: Database) -> Iterator[sessionmaker[Session]]:
    yield session_factory(database.app)
    with database.owner.begin() as connection:
        connection.execute(text("TRUNCATE users, domain_events, jobs CASCADE"))


@pytest.fixture
def session(app_sessions: sessionmaker[Session]) -> Iterator[Session]:
    with app_sessions() as session:
        yield session


@pytest.fixture
def owner_session(database: Database) -> Iterator[Session]:
    with session_factory(database.owner)() as session:
        yield session


@pytest.fixture
def db_settings(database: Database, tmp_path: Path) -> Settings:
    return Settings(
        environment=Environment.TEST,
        database_url=secret(database.app_url),
        job_backoff_base_seconds=30,
        job_backoff_max_seconds=600,
        job_visibility_timeout_seconds=60,
        artifact_storage_dir=tmp_path / "artifacts",
    )


@pytest.fixture(scope="session")
def idp() -> FakeIdentityProvider:
    return FakeIdentityProvider()


@pytest.fixture
def auth_settings() -> AuthSettings:
    return AuthSettings(
        environment=Environment.TEST,
        session_secret=SecretStr("test-session-secret-" + "x" * 24),
        session_cookie_secure=False,
        app_base_url="http://localhost:5173",
        google_client_id=FAKE_CLIENT_ID,
        google_client_secret=SecretStr("test-client-secret"),
    )


@pytest.fixture
def app(
    db_settings: Settings,
    app_sessions: sessionmaker[Session],
    idp: FakeIdentityProvider,
    auth_settings: AuthSettings,
) -> FastAPI:
    application = create_app(
        db_settings,
        session_factory=app_sessions,
        identity_provider=idp,
        review_registry=recording_registry(),
    )
    application.dependency_overrides[get_auth_settings] = lambda: auth_settings
    return application
