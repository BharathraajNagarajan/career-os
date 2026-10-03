import json
from typing import Any

import httpx2
import pytest

from app.llm.providers.anthropic import AnthropicProvider
from app.llm.providers.base import (
    ProviderError,
    ProviderRequest,
    StreamEnd,
    TextDelta,
    Usage,
)
from app.llm.providers.fake import FakeProvider, StreamFailure, sample_from_schema

SCHEMA = {
    "type": "object",
    "properties": {
        "tone": {"type": "string", "enum": ["positive", "neutral"]},
        "count": {"type": "integer"},
    },
    "required": ["tone", "count"],
}


def request(**overrides: Any) -> ProviderRequest:
    fields: dict[str, Any] = {
        "model": "model-x",
        "system": "system text",
        "user": "user text",
        "max_output_tokens": 50,
        "timeout_seconds": 5.0,
    }
    fields.update(overrides)
    return ProviderRequest(**fields)


def test_fake_returns_scripted_text_with_deterministic_usage() -> None:
    provider = FakeProvider(["hello there"])

    result = provider.complete(request())

    assert result.text == "hello there"
    assert result.usage == Usage(input_tokens=5, output_tokens=3)
    assert provider.requests[0].model == "model-x"


def test_fake_builds_a_schema_valid_default_for_structured_requests() -> None:
    result = FakeProvider().complete(request(json_schema=SCHEMA))

    assert json.loads(result.text) == {"tone": "positive", "count": 0}
    assert sample_from_schema({"$defs": {"A": {"type": "boolean"}}, "$ref": "#/$defs/A"}) is False


def test_fake_stream_is_deterministic_and_ends_with_usage() -> None:
    first = list(FakeProvider(["abcdefghijklmnopqrst"]).stream(request()))
    second = list(FakeProvider(["abcdefghijklmnopqrst"]).stream(request()))

    assert first == second
    assert [chunk.text for chunk in first if isinstance(chunk, TextDelta)] == [
        "abcdefgh",
        "ijklmnop",
        "qrst",
    ]
    assert isinstance(first[-1], StreamEnd)


def test_fake_can_fail_before_or_during_a_stream() -> None:
    with pytest.raises(ProviderError, match="provider_down"):
        FakeProvider([ProviderError("provider_down")]).complete(request())

    seen: list[str] = []

    def drain() -> None:
        for chunk in FakeProvider([StreamFailure(after_chunks=1)]).stream(request()):
            if isinstance(chunk, TextDelta):
                seen.append(chunk.text)

    with pytest.raises(ProviderError, match="stream_interrupted"):
        drain()
    assert len(seen) == 1


def message_body(text: str) -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "model-x",
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 12, "output_tokens": 7},
    }


def anthropic_provider(handler: Any) -> AnthropicProvider:
    client = httpx2.Client(transport=httpx2.MockTransport(handler))
    return AnthropicProvider("test-key-not-real", http_client=client)


def test_anthropic_complete_sends_schema_constrained_request_and_reads_usage() -> None:
    captured: list[httpx2.Request] = []

    def handler(http_request: httpx2.Request) -> httpx2.Response:
        captured.append(http_request)
        return httpx2.Response(200, json=message_body('{"tone":"positive","count":1}'))

    result = anthropic_provider(handler).complete(request(json_schema=SCHEMA))

    body = json.loads(captured[0].content)
    assert result.text == '{"tone":"positive","count":1}'
    assert result.usage == Usage(input_tokens=12, output_tokens=7)
    assert body["model"] == "model-x"
    assert body["max_tokens"] == 50
    assert body["system"] == "system text"
    assert body["messages"] == [{"role": "user", "content": "user text"}]
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert "tool_choice" not in body
    assert captured[0].headers["x-api-key"] == "test-key-not-real"


def test_anthropic_does_not_mutate_the_callers_schema() -> None:
    before = json.dumps(SCHEMA, sort_keys=True)

    anthropic_provider(lambda _: httpx2.Response(200, json=message_body("{}"))).complete(
        request(json_schema=SCHEMA)
    )

    assert json.dumps(SCHEMA, sort_keys=True) == before


def test_anthropic_plain_request_has_no_output_format() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(http_request: httpx2.Request) -> httpx2.Response:
        bodies.append(json.loads(http_request.content))
        return httpx2.Response(200, json=message_body("hi"))

    anthropic_provider(handler).complete(request())

    assert "output_config" not in bodies[0]


@pytest.mark.parametrize(
    ("status", "code"),
    [(429, "provider_http_429"), (500, "provider_http_500"), (401, "provider_http_401")],
)
def test_anthropic_http_failures_become_provider_errors(status: int, code: str) -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            status, json={"type": "error", "error": {"type": "x", "message": "m"}}
        )

    with pytest.raises(ProviderError) as error:
        anthropic_provider(handler).complete(request())

    assert error.value.code == code


def test_anthropic_connection_failure_becomes_a_provider_error() -> None:
    def handler(http_request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=http_request)

    with pytest.raises(ProviderError) as error:
        anthropic_provider(handler).complete(request())

    assert error.value.code == "provider_connection"


def test_anthropic_refusal_stop_reason_is_a_provider_error() -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        body = message_body("")
        body["stop_reason"] = "refusal"
        return httpx2.Response(200, json=body)

    with pytest.raises(ProviderError) as error:
        anthropic_provider(handler).complete(request())

    assert error.value.code == "provider_refusal"


def sse(events: list[tuple[str, dict[str, Any]]]) -> bytes:
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events).encode()


def test_anthropic_stream_yields_deltas_then_usage() -> None:
    start = message_body("")
    start["content"] = []
    start["stop_reason"] = None
    events: list[tuple[str, dict[str, Any]]] = [
        ("message_start", {"type": "message_start", "message": start}),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "Hel"},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "lo"},
            },
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"input_tokens": 12, "output_tokens": 2},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]

    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200, content=sse(events), headers={"content-type": "text/event-stream"}
        )

    chunks = list(anthropic_provider(handler).stream(request()))

    assert [chunk.text for chunk in chunks if isinstance(chunk, TextDelta)] == ["Hel", "lo"]
    end = chunks[-1]
    assert isinstance(end, StreamEnd)
    assert end.usage == Usage(input_tokens=12, output_tokens=2)
