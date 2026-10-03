from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    PRODUCTION = "production"


LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class BaseAppSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", frozen=True, case_sensitive=False)

    environment: Environment = Environment.LOCAL
    log_level: LogLevel = "INFO"
    log_json: bool = True

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION


class ModelPrice(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_usd_per_mtok: Decimal = Field(ge=0)
    output_usd_per_mtok: Decimal = Field(ge=0)


JD_MAX_CHARS_CEILING = 200_000
FAKE_FAST_MODEL = "fake-fast"
FAKE_REASONING_MODEL = "fake-reasoning"


def _fake_prices() -> dict[str, ModelPrice]:
    price = ModelPrice(input_usd_per_mtok=Decimal("1"), output_usd_per_mtok=Decimal("5"))
    return {FAKE_FAST_MODEL: price, FAKE_REASONING_MODEL: price}


class Settings(BaseAppSettings):
    database_url: SecretStr
    cors_allowed_origins: list[str] = Field(default_factory=list)
    worker_poll_interval_seconds: float = Field(default=5.0, gt=0)
    job_visibility_timeout_seconds: float = Field(default=900.0, gt=0)
    job_backoff_base_seconds: float = Field(default=10.0, gt=0)
    job_backoff_max_seconds: float = Field(default=3600.0, gt=0)
    llm_daily_cost_cap_usd: Decimal = Field(default=Decimal("1.00"), ge=0, decimal_places=2)
    llm_provider: Literal["fake", "anthropic"] = "fake"
    anthropic_api_key: SecretStr | None = None
    llm_model_fast: str = FAKE_FAST_MODEL
    llm_model_reasoning: str = FAKE_REASONING_MODEL
    llm_model_prices: dict[str, ModelPrice] = Field(default_factory=_fake_prices)
    llm_request_timeout_seconds: float = Field(default=60.0, gt=0)
    llm_default_max_output_tokens: int = Field(default=1024, gt=0)
    artifact_storage_dir: Path = Path("/srv/artifacts")
    resume_max_bytes: int = Field(default=5 * 1024 * 1024, gt=0)
    resume_max_pages: int = Field(default=10, gt=0)
    parse_timeout_seconds: float = Field(default=30.0, gt=0)
    extracted_text_max_chars: int = Field(default=200_000, gt=0)
    jd_min_chars: int = Field(default=200, ge=1)
    jd_max_chars: int = Field(default=50_000, gt=0, le=JD_MAX_CHARS_CEILING)
    jd_extraction_max_output_tokens: int = Field(default=6000, gt=0)

    @model_validator(mode="after")
    def _check_jd_limits(self) -> Self:
        if self.jd_min_chars > self.jd_max_chars:
            raise ValueError("JD_MIN_CHARS must not exceed JD_MAX_CHARS")
        return self

    @model_validator(mode="after")
    def _check_llm_configuration(self) -> Self:
        for tier_model in (self.llm_model_fast, self.llm_model_reasoning):
            if tier_model not in self.llm_model_prices:
                raise ValueError(f"LLM_MODEL_PRICES has no entry for model {tier_model!r}")
        if self.llm_provider == "anthropic" and not (
            self.anthropic_api_key and self.anthropic_api_key.get_secret_value()
        ):
            raise ValueError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")
        return self


class AuthSettings(BaseAppSettings):
    session_secret: SecretStr = Field(min_length=32)
    session_idle_timeout_hours: float = Field(default=168, gt=0)
    session_absolute_timeout_hours: float = Field(default=720, gt=0)
    session_cookie_secure: bool = True
    app_base_url: str = "http://localhost:5173"
    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")

    @property
    def google_redirect_uri(self) -> str:
        return f"{self.app_base_url.rstrip('/')}/api/v1/auth/google/callback"


class MigrationSettings(BaseAppSettings):
    migration_database_url: SecretStr


class BootstrapSettings(MigrationSettings):
    app_db_password: SecretStr = Field(min_length=12)


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_auth_settings() -> AuthSettings:
    return AuthSettings()
