from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.llm.config import LlmConfig
from app.llm.gateway import Clock, ModelGateway, utc_now
from app.llm.prompts.catalog import default_registry
from app.llm.prompts.registry import PromptRegistry
from app.llm.providers.base import ModelProvider
from app.llm.providers.fake import FakeProvider


def build_provider(settings: Settings) -> ModelProvider:
    if settings.llm_provider == "anthropic":
        from app.llm.providers.anthropic import AnthropicProvider

        assert settings.anthropic_api_key is not None  # noqa: S101
        return AnthropicProvider(settings.anthropic_api_key.get_secret_value())
    return FakeProvider()


def build_gateway(
    settings: Settings,
    session_factory: sessionmaker[Session],
    *,
    provider: ModelProvider | None = None,
    prompts: PromptRegistry | None = None,
    clock: Clock = utc_now,
) -> ModelGateway:
    return ModelGateway(
        session_factory=session_factory,
        provider=provider or build_provider(settings),
        config=LlmConfig.from_settings(settings),
        prompts=prompts or default_registry(),
        clock=clock,
    )
