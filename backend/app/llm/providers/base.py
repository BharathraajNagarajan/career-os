from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Protocol

from app.db.models import LlmProviderName


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class ProviderRequest:
    model: str
    system: str
    user: str
    max_output_tokens: int
    timeout_seconds: float
    json_schema: dict[str, Any] | None = None


@dataclass(frozen=True)
class ProviderResult:
    text: str
    usage: Usage


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class StreamEnd:
    usage: Usage


StreamChunk = TextDelta | StreamEnd


class ProviderError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ModelProvider(Protocol):
    name: LlmProviderName

    def complete(self, request: ProviderRequest) -> ProviderResult: ...

    def stream(self, request: ProviderRequest) -> Iterator[StreamChunk]: ...
