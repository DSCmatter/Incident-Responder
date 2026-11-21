"""Offline proof of the four client promises: one live call per transcript, a
budget that falls through, replay that cannot spend, and a row per decision.

Every test uses a transport that returns recorded payloads, so the suite runs
with no key, no network, and no provider SDK.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config import (
    Mode,
    ModelPrice,
)
from llm.client import Completion, cache_key
from llm.errors import LlmError, LlmUnavailable, ProviderError, QuotaExhausted, ReplayMiss
from llm.ledger import CallStatus
from llm.transport import HttpRequest, HttpxTransport
from llm.turn import (
    Finish,
    ModelCall,
    ModelReply,
    Role,
    TextPart,
    ToolCall,
    ToolCallPart,
    ToolResult,
    ToolResultPart,
    ToolSpec,
    Turn,
    Usage,
)
from tests.support import (
    GEMINI_REPLY,
    OPENAI_REPLY,
    ExplodingTransport,
    StubTransport,
    ask,
    client_for,
    settings_for,
)


def test_second_identical_call_costs_no_quota(tmp_path: Path) -> None:
    transport = StubTransport(GEMINI_REPLY)
    client = client_for(tmp_path, settings_for(), transport)
    try:
        first = client.complete(ask())
        second = client.complete(ask())
        assert len(transport.requests) == 1
        assert first.cache_hit is False
        assert second.cache_hit is True
        assert second.reply.text == "deploy removed the env var"
        assert client.ledger.spent_today("gemini") == 1
        statuses = [row.status for row in client.ledger.rows("run-1")]
        assert statuses == [CallStatus.ok.value, CallStatus.hit.value]
    finally:
        client.close()


def test_budget_switches_to_the_next_backend(tmp_path: Path) -> None:
    settings = settings_for(chain=("gemini", "openrouter"), budgets={"gemini": 1, "openrouter": 5})
    transport = StubTransport(GEMINI_REPLY, OPENAI_REPLY)
    client = client_for(tmp_path, settings, transport)
    try:
        assert client.complete(ask("first")).backend == "gemini"
        second = client.complete(ask("second"))
        assert second.backend == "openrouter"
        assert client.ledger.spent_today("gemini") == 1
        assert client.ledger.spent_today("openrouter") == 1
        skipped = [row for row in client.ledger.rows("run-1") if row.status == "skipped"]
        assert len(skipped) == 1 and "1/1" in skipped[0].detail
    finally:
        client.close()


def test_every_budget_spent_raises_quota_exhausted(tmp_path: Path) -> None:
    settings = settings_for(chain=("gemini", "openrouter"), budgets={"gemini": 0, "openrouter": 0})
    transport = StubTransport()
    client = client_for(tmp_path, settings, transport)
    try:
        with pytest.raises(QuotaExhausted, match="gemini 0/0, openrouter 0/0"):
            client.complete(ask())
        assert transport.requests == []
    finally:
        client.close()


def test_record_then_replay_never_calls_out(tmp_path: Path) -> None:
    recording = client_for(
        tmp_path, settings_for(mode=Mode.record), StubTransport(GEMINI_REPLY), run_id="rec"
    )
    try:
        recording.complete(ask())
    finally:
        recording.close()

    replaying = client_for(
        tmp_path, settings_for(mode=Mode.replay), ExplodingTransport(), run_id="rep"
    )
    try:
        result = replaying.complete(ask())
        assert result.cache_hit is True
        assert result.reply.text == "deploy removed the env var"
        assert sum(row.quota_spent for row in replaying.ledger.rows("rep")) == 0
    finally:
        replaying.close()


def test_replay_miss_names_what_to_record(tmp_path: Path) -> None:
    client = client_for(
        tmp_path,
        settings_for(mode=Mode.replay, chain=("gemini", "openrouter")),
        ExplodingTransport(),
    )
    try:
        with pytest.raises(ReplayMiss) as caught:
            client.complete(ask())
        message = str(caught.value)
        assert cache_key(ask())[:12] in message
        assert "gemini, openrouter" in message
        assert "triage" in message
        assert "run-1" in message
        assert "INCIDENT_LLM_MODE=record" in message
    finally:
        client.close()


def test_retryable_failure_falls_through_to_the_next_backend(tmp_path: Path) -> None:
    settings = settings_for(chain=("gemini", "openrouter"))
    transport = StubTransport(ProviderError(status=503, body="overloaded"), OPENAI_REPLY)
    client = client_for(tmp_path, settings, transport)
    try:
        result = client.complete(ask())
        assert result.backend == "openrouter"
        assert len(transport.requests) == 2
        assert client.ledger.rows("run-1")[0].status == CallStatus.error.value
    finally:
        client.close()


def test_payload_bug_does_not_fall_through(tmp_path: Path) -> None:
    settings = settings_for(chain=("gemini", "openrouter"))
    transport = StubTransport(ProviderError(status=400, body="bad tool schema"), OPENAI_REPLY)
    client = client_for(tmp_path, settings, transport)
    try:
        with pytest.raises(LlmError, match="rejected the request"):
            client.complete(ask())
        assert len(transport.requests) == 1
    finally:
        client.close()


def test_fallback_models_tried_before_leaving_a_backend(tmp_path: Path) -> None:
    settings = settings_for(fallbacks={"gemini": ["gemini-test-lite"]})
    transport = StubTransport(GEMINI_REPLY)
    client = client_for(tmp_path, settings, transport)
    try:
        client.complete(ask())
        assert "gemini-test" in transport.requests[0].url
    finally:
        client.close()


def test_row_carries_tokens_latency_and_cost(tmp_path: Path) -> None:
    price = ModelPrice(input_per_mtok=1.0, output_per_mtok=2.0)
    settings = settings_for(pricing={"gemini-test": price})
    client = client_for(tmp_path, settings, StubTransport(GEMINI_REPLY))
    try:
        client.complete(ask())
        [row] = client.ledger.rows("run-1")
        assert (row.tokens_in, row.tokens_out) == (1000, 500)
        assert row.cost_usd_equiv == pytest.approx(0.001 + 0.001)
        assert row.quota_spent == 1
        assert row.cache_key == cache_key(ask())
    finally:
        client.close()


def test_unknown_model_costs_zero(tmp_path: Path) -> None:
    client = client_for(tmp_path, settings_for(), StubTransport(GEMINI_REPLY))
    try:
        client.complete(ask())
        [row] = client.ledger.rows("run-1")
        assert row.cost_usd_equiv == 0.0
    finally:
        client.close()


def test_cache_key_tracks_content_not_backend_or_agent() -> None:
    base = ask()
    assert cache_key(base) == cache_key(ask(agent="diagnosis"))
    assert cache_key(base) != cache_key(ask("different question"))
    with_tool = ModelCall(
        agent="triage",
        system="be terse",
        turns=(Turn(Role.user, (TextPart("why is checkout down"),)),),
        tools=(ToolSpec(name="query_logs", description="logs", parameters={"type": "object"}),),
    )
    assert cache_key(base) != cache_key(with_tool)


def test_hits_count_as_turns_so_replay_costs_what_live_cost(tmp_path: Path) -> None:
    client = client_for(tmp_path, settings_for(), StubTransport(GEMINI_REPLY))
    try:
        client.complete(ask())
        client.complete(ask())
        assert client.turns() == 2
    finally:
        client.close()


def test_http_transport_refuses_the_network_inside_a_test() -> None:
    request = HttpRequest(url="https://gemini.test/x", headers={}, body={}, timeout_s=1.0)
    with pytest.raises(LlmError, match="disabled while a test is running"):
        HttpxTransport().post(request)


def test_gemini_body_shape_and_thought_signature_echo(tmp_path: Path) -> None:
    reply = {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [
                        {"text": "checking logs", "thought": True},
                        {
                            "functionCall": {"id": "c1", "name": "query_logs", "args": {"q": "x"}},
                            "thoughtSignature": "sig-1",
                        },
                    ],
                },
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 20,
            "candidatesTokenCount": 8,
            "thoughtsTokenCount": 12,
        },
    }
    transport = StubTransport(reply)
    client = client_for(tmp_path, settings_for(), transport)
    try:
        result = client.complete(ask())
    finally:
        client.close()

    assert result.reply.finish is Finish.tool_calls
    assert result.reply.usage.output_tokens == 20
    call = result.reply.tool_calls[0]
    assert (call.id, call.name, call.args) == ("c1", "query_logs", {"q": "x"})

    follow_up = ModelCall(
        agent="diagnosis",
        system="be terse",
        turns=(
            Turn(Role.model, (ToolCallPart(call=call, opaque="sig-1"),)),
            Turn(Role.user, (ToolResultPart(ToolResult("c1", "query_logs", {"lines": 3})),)),
        ),
    )
    transport2 = StubTransport(GEMINI_REPLY)
    echoed = client_for(tmp_path, settings_for(), transport2, run_id="run-2")
    try:
        echoed.complete(follow_up)
    finally:
        echoed.close()
    contents = transport2.requests[0].body["contents"]
    assert contents[0]["parts"][0]["functionCall"]["id"] == "c1"
    assert contents[0]["parts"][0]["thoughtSignature"] == "sig-1"
    assert contents[1]["role"] == "user"
    assert contents[1]["parts"][0]["functionResponse"]["id"] == "c1"
    assert contents[1]["parts"][0]["functionResponse"]["response"] == {"lines": 3}


def test_openai_body_shape_and_tool_arguments(tmp_path: Path) -> None:
    transport = StubTransport(OPENAI_REPLY)
    client = client_for(tmp_path, settings_for(chain=("openrouter",)), transport)
    call = ask()
    try:
        client.complete(call)
    finally:
        client.close()
    body = transport.requests[0].body
    assert body["messages"][0] == {"role": "system", "content": "be terse"}
    assert body["messages"][1]["role"] == "user"
    assert transport.requests[0].url.endswith("/chat/completions")


def test_openai_renders_tool_results_and_parses_calls(tmp_path: Path) -> None:
    reply = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "c9",
                            "function": {"name": "query_logs", "arguments": '{"q": "oom"}'},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 7, "completion_tokens": 9},
    }
    transport = StubTransport(reply)
    client = client_for(tmp_path, settings_for(chain=("openrouter",)), transport)
    try:
        result = client.complete(ask())
        rendered = transport.requests[0].body["messages"]
    finally:
        client.close()
    assert result.reply.tool_calls[0].args == {"q": "oom"}
    assert rendered[1] == {"role": "user", "content": "why is checkout down"}

    follow_up = ModelCall(
        agent="diagnosis",
        system="be terse",
        turns=(
            Turn(Role.model, (ToolCallPart(ToolCall("c9", "query_logs", {"q": "oom"})),)),
            Turn(Role.user, (ToolResultPart(ToolResult("c9", "query_logs", {"lines": 2})),)),
        ),
    )
    transport2 = StubTransport(OPENAI_REPLY)
    client = client_for(tmp_path, settings_for(chain=("openrouter",)), transport2, run_id="run-2")
    try:
        client.complete(follow_up)
        messages = transport2.requests[0].body["messages"]
    finally:
        client.close()
    assert messages[1]["tool_calls"][0]["function"]["arguments"] == '{"q": "oom"}'
    assert messages[2]["role"] == "tool"
    assert messages[2]["tool_call_id"] == "c9"


def test_malformed_tool_arguments_are_an_error(tmp_path: Path) -> None:
    reply = {
        "choices": [
            {
                "message": {
                    "tool_calls": [{"id": "c1", "function": {"name": "x", "arguments": "{oops"}}]
                },
                "finish_reason": "tool_calls",
            }
        ]
    }
    client = client_for(tmp_path, settings_for(chain=("openrouter",)), StubTransport(reply))
    try:
        with pytest.raises(LlmError, match="tool arguments were not JSON"):
            client.complete(ask())
    finally:
        client.close()


def test_no_usable_backend_is_reported(tmp_path: Path) -> None:
    settings = settings_for(gemini_key_env="INCIDENT_TEST_KEY_THAT_IS_UNSET")
    client = client_for(tmp_path, settings, StubTransport())
    try:
        with pytest.raises(LlmUnavailable, match="no backend is configured"):
            client.complete(ask())
    finally:
        client.close()


def test_completion_exposes_the_winning_backend(tmp_path: Path) -> None:
    client = client_for(tmp_path, settings_for(), StubTransport(GEMINI_REPLY))
    try:
        result: Completion = client.complete(ask())
        assert (result.backend, result.model, result.cache_hit) == ("gemini", "gemini-test", False)
        assert isinstance(result.reply, ModelReply)
        assert result.reply.usage == Usage(
            input_tokens=1000, output_tokens=500, cached_input_tokens=0
        )
    finally:
        client.close()
