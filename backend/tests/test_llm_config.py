from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.db.models import LlmProviderName, LlmTier
from app.llm.config import LlmConfig

REQUIRED_ENV = "postgresql://career:secret-value@db:5432/career"

PRICES = (
    '{"model-a":{"input_usd_per_mtok":"1","output_usd_per_mtok":"5"},'
    '"model-b":{"input_usd_per_mtok":"2.5","output_usd_per_mtok":"10"}}'
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "LLM_PROVIDER",
        "ANTHROPIC_API_KEY",
        "LLM_MODEL_FAST",
        "LLM_MODEL_REASONING",
        "LLM_MODEL_PRICES",
        "LLM_REQUEST_TIMEOUT_SECONDS",
        "LLM_DAILY_COST_CAP_USD",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_URL", REQUIRED_ENV)


def test_provider_defaults_to_fake_and_needs_no_key() -> None:
    settings = Settings()

    assert settings.llm_provider == "fake"
    assert settings.anthropic_api_key is None
    assert LlmConfig.from_settings(settings).provider is LlmProviderName.FAKE


def test_tiers_and_prices_come_from_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL_FAST", "model-a")
    monkeypatch.setenv("LLM_MODEL_REASONING", "model-b")
    monkeypatch.setenv("LLM_MODEL_PRICES", PRICES)

    config = LlmConfig.from_settings(Settings())

    assert config.model_for(LlmTier.FAST) == "model-a"
    assert config.model_for(LlmTier.REASONING) == "model-b"
    assert config.price_for("model-b").output_usd_per_mtok == Decimal("10")


def test_a_tier_model_without_a_price_fails_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL_FAST", "model-a")
    monkeypatch.setenv("LLM_MODEL_PRICES", PRICES)

    with pytest.raises(ValidationError, match="no entry for model"):
        Settings()


def test_anthropic_provider_requires_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_MODEL_FAST", "model-a")
    monkeypatch.setenv("LLM_MODEL_REASONING", "model-b")
    monkeypatch.setenv("LLM_MODEL_PRICES", PRICES)

    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY is required"):
        Settings()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    settings = Settings()
    assert settings.anthropic_api_key is not None
    assert "test-key-not-real" not in repr(settings)


def test_unknown_provider_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "other")

    with pytest.raises(ValidationError):
        Settings()


def test_negative_price_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "LLM_MODEL_PRICES",
        '{"fake-fast":{"input_usd_per_mtok":"-1","output_usd_per_mtok":"1"},'
        '"fake-reasoning":{"input_usd_per_mtok":"1","output_usd_per_mtok":"1"}}',
    )

    with pytest.raises(ValidationError):
        Settings()
