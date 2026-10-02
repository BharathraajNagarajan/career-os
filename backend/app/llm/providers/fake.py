import json
import math
import threading
from collections import deque
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

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

CHUNK_CHARS = 8
DEFAULT_REPLY = "This is a deterministic synthetic reply."


@dataclass(frozen=True)
class StreamFailure:
    after_chunks: int = 0


Scripted = str | ProviderError | StreamFailure


def sample_from_schema(schema: dict[str, Any]) -> Any:
    definitions = schema.get("$defs", {})

    def build(node: dict[str, Any]) -> Any:
        if "$ref" in node:
            return build(definitions[node["$ref"].rsplit("/", 1)[-1]])
        if "enum" in node:
            return node["enum"][0]
        kind = node.get("type")
        if kind == "object":
            return {name: build(child) for name, child in node.get("properties", {}).items()}
        if kind == "array":
            return []
        if kind == "integer":
            return 0
        if kind == "number":
            return 0.0
        if kind == "boolean":
            return False
        return "fake"

    return build(schema)


def count_tokens(text: str) -> int:
    return max(1, math.ceil(len(text.encode("utf-8")) / 4))


class FakeProvider:
    name = LlmProviderName.FAKE

    def __init__(self, script: Iterable[Scripted] = ()) -> None:
        self._script: deque[Scripted] = deque(script)
        self._lock = threading.Lock()
        self.requests: list[ProviderRequest] = []

    def _next(self, request: ProviderRequest) -> Scripted:
        with self._lock:
            self.requests.append(request)
            if self._script:
                return self._script.popleft()
        if request.json_schema is not None:
            return json.dumps(sample_from_schema(request.json_schema))
        return DEFAULT_REPLY

    def _usage(self, request: ProviderRequest, text: str) -> Usage:
        return Usage(
            input_tokens=count_tokens(request.system + request.user),
            output_tokens=min(count_tokens(text), request.max_output_tokens),
        )

    def complete(self, request: ProviderRequest) -> ProviderResult:
        scripted = self._next(request)
        if isinstance(scripted, ProviderError):
            raise scripted
        text = DEFAULT_REPLY if isinstance(scripted, StreamFailure) else scripted
        return ProviderResult(text=text, usage=self._usage(request, text))

    def stream(self, request: ProviderRequest) -> Iterator[StreamChunk]:
        scripted = self._next(request)
        if isinstance(scripted, ProviderError):
            raise scripted
        text = DEFAULT_REPLY if isinstance(scripted, StreamFailure) else scripted
        chunks = [text[i : i + CHUNK_CHARS] for i in range(0, len(text), CHUNK_CHARS)]
        for index, chunk in enumerate(chunks):
            if isinstance(scripted, StreamFailure) and index >= scripted.after_chunks:
                raise ProviderError("stream_interrupted")
            yield TextDelta(chunk)
        if isinstance(scripted, StreamFailure):
            raise ProviderError("stream_interrupted")
        yield StreamEnd(self._usage(request, text))
