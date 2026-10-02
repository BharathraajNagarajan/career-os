from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import BootstrapSettings, Environment, MigrationSettings, Settings

REQUIRED_ENV = "postgresql://career:secret-value@db:5432/career"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "DATABASE_URL",
        "ENVIRONMENT",
        "LLM_DAILY_COST_CAP_USD",
        "CORS_ALLOWED_ORIGINS",
        "WORKER_POLL_INTERVAL_SECONDS",
        "MIGRATION_DATABASE_URL",
        "APP_DB_PASSWORD",
        "JOB_VISIBILITY_TIMEOUT_SECONDS",
        "JOB_BACKOFF_BASE_SECONDS",
        "JOB_BACKOFF_MAX_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_loads_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", REQUIRED_ENV)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", '["http://localhost:5173"]')

    settings = Settings()

    assert settings.environment is Environment.PRODUCTION
    assert settings.is_production
    assert settings.database_url.get_secret_value() == REQUIRED_ENV
    assert settings.cors_allowed_origins == ["http://localhost:5173"]


def test_database_url_is_required() -> None:
    with pytest.raises(ValidationError):
        Settings()


def test_dotenv_file_is_never_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text(f"DATABASE_URL={REQUIRED_ENV}\n")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValidationError):
        Settings()


def test_database_url_is_hidden_from_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", REQUIRED_ENV)

    settings = Settings()

    assert "secret-value" not in repr(settings)
    assert "secret-value" not in str(settings.model_dump())


def test_llm_daily_cost_cap_defaults_to_one_dollar(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", REQUIRED_ENV)

    assert Settings().llm_daily_cost_cap_usd == Decimal("1.00")


def test_llm_daily_cost_cap_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", REQUIRED_ENV)
    monkeypatch.setenv("LLM_DAILY_COST_CAP_USD", "2.50")

    assert Settings().llm_daily_cost_cap_usd == Decimal("2.50")


@pytest.mark.parametrize("value", ["-1", "0.001", "not-a-number"])
def test_llm_daily_cost_cap_rejects_invalid_values(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", REQUIRED_ENV)
    monkeypatch.setenv("LLM_DAILY_COST_CAP_USD", value)

    with pytest.raises(ValidationError):
        Settings()


def test_worker_poll_interval_must_be_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", REQUIRED_ENV)
    monkeypatch.setenv("WORKER_POLL_INTERVAL_SECONDS", "0")

    with pytest.raises(ValidationError):
        Settings()


def test_runtime_settings_do_not_require_migration_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", REQUIRED_ENV)

    settings = Settings()

    assert not hasattr(settings, "migration_database_url")
    assert not hasattr(settings, "app_db_password")
    assert settings.job_backoff_base_seconds < settings.job_backoff_max_seconds


def test_migration_settings_require_their_own_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", REQUIRED_ENV)

    with pytest.raises(ValidationError):
        MigrationSettings()


def test_bootstrap_settings_hide_the_app_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIGRATION_DATABASE_URL", REQUIRED_ENV)
    monkeypatch.setenv("APP_DB_PASSWORD", "app-password-value")

    settings = BootstrapSettings()

    assert "app-password-value" not in repr(settings)
    assert "secret-value" not in repr(settings)


def test_bootstrap_settings_reject_short_app_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIGRATION_DATABASE_URL", REQUIRED_ENV)
    monkeypatch.setenv("APP_DB_PASSWORD", "short")

    with pytest.raises(ValidationError):
        BootstrapSettings()
