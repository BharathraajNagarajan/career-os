import copy
from collections.abc import Iterator
from typing import Any

import anthropic

from app.db.models import LlmProviderName
from app.llm.providers.base import (
    ProviderError,
    ProviderRequest,
    ProviderResult,
    StreamChunk,
    StreamEnd,
    TextDelta,
    Usage,
)


def _translate(exc: Exception) -> ProviderError:
    if isinstance(exc, anthropic.APITimeoutError):
        return ProviderError("provider_timeout")
    if isinstance(exc, anthropic.APIConnectionError):
        return ProviderError("provider_connection")
    if isinstance(exc, anthropic.APIStatusError):
        return ProviderError(f"provider_http_{exc.status_code}")
    return ProviderError("provider_error")


def _usage(raw: Any) -> Usage:
    return Usage(input_tokens=int(raw.input_tokens), output_tokens=int(raw.output_tokens))


class AnthropicProvider:
    name = LlmProviderName.ANTHROPIC

    def __init__(self, api_key: str, *, http_client: Any | None = None) -> None:
        self._client = anthropic.Anthropic(api_key=api_key, max_retries=0, http_client=http_client)

    def _arguments(self, request: ProviderRequest) -> dict[str, Any]:
        arguments: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_output_tokens,
            "system": request.system,
            "messages": [{"role": "user", "content": request.user}],
            "timeout": request.timeout_seconds,
        }
        if request.json_schema is not None:
            arguments["output_config"] = {
                "format": {
                    "type": "json_schema",
                    "schema": anthropic.transform_schema(copy.deepcopy(request.json_schema)),
                }
            }
        return arguments

    def complete(self, request: ProviderRequest) -> ProviderResult:
        try:
            response = self._client.messages.create(**self._arguments(request))
        except anthropic.APIError as exc:
            raise _translate(exc) from None
        if response.stop_reason == "refusal":
            raise ProviderError("provider_refusal")
        text = "".join(block.text for block in response.content if block.type == "text")
        return ProviderResult(text=text, usage=_usage(response.usage))

    def stream(self, request: ProviderRequest) -> Iterator[StreamChunk]:
        try:
            with self._client.messages.stream(**self._arguments(request)) as stream:
                for delta in stream.text_stream:
                    yield TextDelta(delta)
                final = stream.get_final_message()
        except anthropic.APIError as exc:
            raise _translate(exc) from None
        if final.stop_reason == "refusal":
            raise ProviderError("provider_refusal")
        yield StreamEnd(_usage(final.usage))
