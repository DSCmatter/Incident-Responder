"""OpenAI-compatible chat completions, which is what OpenRouter and Ollama speak.

Three shape differences from Gemini, each a silent-corruption risk if guessed:
tool arguments are a JSON *string*, each tool result is its own `role: tool`
message keyed by `tool_call_id`, and function parameters use `parameters`.
"""

from __future__ import annotations

import json

from config import BackendConfig
from llm.errors import LlmError
from llm.transport import HttpRequest
from llm.turn import (
    Finish,
    Json,
    ModelCall,
    ModelReply,
    Part,
    Role,
    TextPart,
    ToolCall,
    ToolCallPart,
    ToolResultPart,
    Turn,
    Usage,
)
from llm.wire import portable_schema


def render(call: ModelCall, backend: BackendConfig) -> HttpRequest:
    body: Json = {
        "model": backend.model,
        "temperature": call.temperature,
        "max_tokens": call.max_output_tokens,
        "messages": [{"role": "system", "content": call.system}],
    }
    messages: list[Json] = body["messages"]
    for turn in call.turns:
        messages.extend(_render_turn(turn))
    if call.tools:
        body["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": portable_schema(spec.parameters),
                },
            }
            for spec in call.tools
        ]
    headers = {"content-type": "application/json"}
    if backend.api_key_env is not None:
        headers["authorization"] = f"Bearer {backend.api_key() or ''}"
    return HttpRequest(
        url=f"{backend.base_url.rstrip('/')}/chat/completions",
        headers=headers,
        body=body,
        timeout_s=backend.timeout_seconds,
    )


def parse(payload: Json) -> ModelReply:
    choices = payload.get("choices") or []
    if not choices:
        raise LlmError(f"openai-compatible reply carried no choice: {payload}")
    message = choices[0].get("message") or {}
    parts: list[Part] = []
    text = message.get("content")
    if isinstance(text, str) and text:
        parts.append(TextPart(text=text))
    for index, raw in enumerate(message.get("tool_calls") or []):
        function = raw.get("function") or {}
        parts.append(
            ToolCallPart(
                call=ToolCall(
                    id=raw.get("id") or f"call_{index}",
                    name=function["name"],
                    args=_arguments(function.get("arguments")),
                )
            )
        )
    if not parts:
        raise LlmError(f"openai-compatible message had no content and no tool calls: {message}")
    return ModelReply(
        parts=tuple(parts),
        finish=_finish(
            choices[0].get("finish_reason"),
            has_calls=any(isinstance(part, ToolCallPart) for part in parts),
        ),
        usage=_usage(payload),
    )


def _render_turn(turn: Turn) -> list[Json]:
    if turn.role is Role.model:
        text = "".join(part.text for part in turn.parts if isinstance(part, TextPart))
        calls = [
            {
                "id": part.call.id,
                "type": "function",
                "function": {
                    "name": part.call.name,
                    "arguments": json.dumps(dict(part.call.args)),
                },
            }
            for part in turn.parts
            if isinstance(part, ToolCallPart)
        ]
        message: Json = {"role": "assistant", "content": text or None}
        if calls:
            message["tool_calls"] = calls
        return [message]

    rendered: list[Json] = []
    text = "".join(part.text for part in turn.parts if isinstance(part, TextPart))
    if text:
        rendered.append({"role": "user", "content": text})
    for part in turn.parts:
        if isinstance(part, ToolResultPart):
            rendered.append(
                {
                    "role": "tool",
                    "tool_call_id": part.result.call_id,
                    "name": part.result.name,
                    "content": json.dumps(dict(part.result.payload)),
                }
            )
    if not rendered:
        raise LlmError("a user turn with no text and no tool result cannot be sent to openai")
    return rendered


def _arguments(raw: object) -> dict[str, object]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LlmError(f"tool arguments were not JSON: {raw!r}") from exc
    if not isinstance(parsed, dict):
        raise LlmError(f"tool arguments were {type(parsed).__name__}, not an object: {raw!r}")
    return parsed


def _finish(reason: str | None, *, has_calls: bool) -> Finish:
    match reason:
        case "length":
            return Finish.length
        case "content_filter":
            return Finish.blocked
        case "tool_calls":
            return Finish.tool_calls
        case "error":
            return Finish.error
        case _:
            return Finish.tool_calls if has_calls else Finish.stop


def _usage(payload: Json) -> Usage:
    usage = payload.get("usage") or {}
    details = usage.get("prompt_tokens_details") or {}
    return Usage(
        input_tokens=int(usage.get("prompt_tokens", 0)),
        output_tokens=int(usage.get("completion_tokens", 0)),
        cached_input_tokens=int(details.get("cached_tokens", 0)),
    )
