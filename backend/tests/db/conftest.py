import os
import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from app.config import Environment, Settings
from app.core.db import database_url, session_factory
from app.db.bootstrap import APP_ROLE, bootstrap

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
def db_settings(database: Database) -> Settings:
    return Settings(
        environment=Environment.TEST,
        database_url=secret(database.app_url),
        job_backoff_base_seconds=30,
        job_backoff_max_seconds=600,
        job_visibility_timeout_seconds=60,
    )
