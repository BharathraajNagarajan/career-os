from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from app.config import ModelPrice, Settings
from app.db.models import LlmProviderName, LlmTier


@dataclass(frozen=True)
class LlmConfig:
    provider: LlmProviderName
    models: Mapping[LlmTier, str]
    prices: Mapping[str, ModelPrice]
    daily_cap_usd: Decimal
    timeout_seconds: float

    @classmethod
    def from_settings(cls, settings: Settings) -> "LlmConfig":
        return cls(
            provider=LlmProviderName(settings.llm_provider),
            models={
                LlmTier.FAST: settings.llm_model_fast,
                LlmTier.REASONING: settings.llm_model_reasoning,
            },
            prices=dict(settings.llm_model_prices),
            daily_cap_usd=settings.llm_daily_cost_cap_usd,
            timeout_seconds=settings.llm_request_timeout_seconds,
        )

    def model_for(self, tier: LlmTier) -> str:
        return self.models[tier]

    def price_for(self, model: str) -> ModelPrice:
        return self.prices[model]
