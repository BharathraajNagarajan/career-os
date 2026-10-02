from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
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


class Settings(BaseAppSettings):
    database_url: SecretStr
    cors_allowed_origins: list[str] = Field(default_factory=list)
    worker_poll_interval_seconds: float = Field(default=5.0, gt=0)
    job_visibility_timeout_seconds: float = Field(default=900.0, gt=0)
    job_backoff_base_seconds: float = Field(default=10.0, gt=0)
    job_backoff_max_seconds: float = Field(default=3600.0, gt=0)
    llm_daily_cost_cap_usd: Decimal = Field(default=Decimal("1.00"), ge=0, decimal_places=2)


class MigrationSettings(BaseAppSettings):
    migration_database_url: SecretStr


class BootstrapSettings(MigrationSettings):
    app_db_password: SecretStr = Field(min_length=12)


@lru_cache
def get_settings() -> Settings:
    return Settings()
