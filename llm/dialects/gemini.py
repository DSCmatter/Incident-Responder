"""Gemini generateContent, rendered from and parsed into the neutral wire.

`systemInstruction` is a Content, `parametersJsonSchema` is the field that takes a
real JSON Schema, and a function response rides on a `user` turn. Those three are
where a hand-written body usually goes wrong, so each has a test.
"""

from __future__ import annotations

from typing import Any

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
        "systemInstruction": {"parts": [{"text": call.system}]},
        "contents": [_render_turn(turn) for turn in call.turns],
        "generationConfig": {
            "temperature": call.temperature,
            "maxOutputTokens": call.max_output_tokens,
        },
    }
    if call.tools:
        body["tools"] = [
            {
                "functionDeclarations": [
                    {
                        "name": spec.name,
                        "description": spec.description,
                        "parametersJsonSchema": portable_schema(spec.parameters),
                    }
                    for spec in call.tools
                ]
            }
        ]
    headers = {"content-type": "application/json"}
    if backend.api_key_env is not None:
        headers["x-goog-api-key"] = backend.api_key() or ""
    return HttpRequest(
        url=f"{backend.base_url.rstrip('/')}/models/{backend.model}:generateContent",
        headers=headers,
        body=body,
        timeout_s=backend.timeout_seconds,
    )


def parse(payload: Json) -> ModelReply:
    block = payload.get("promptFeedback", {}).get("blockReason")
    if block:
        return ModelReply(parts=(), finish=Finish.blocked, usage=_usage(payload))
    candidates = payload.get("candidates") or []
    if not candidates:
        raise LlmError(f"gemini replied without a candidate: {payload}")
    candidate = candidates[0]
    parts = _parse_parts(candidate.get("content", {}).get("parts") or [])
    finish = _finish(candidate.get("finishReason"), has_calls=any(_is_call(p) for p in parts))
    return ModelReply(parts=parts, finish=finish, usage=_usage(payload))


def _render_turn(turn: Turn) -> Json:
    parts = []
    for part in turn.parts:
        if isinstance(part, TextPart):
            piece: Json = {"text": part.text}
            if part.thought:
                piece["thought"] = True
            if part.opaque:
                piece["thoughtSignature"] = part.opaque
            parts.append(piece)
        elif isinstance(part, ToolCallPart):
            piece = {
                "functionCall": {
                    "id": part.call.id,
                    "name": part.call.name,
                    "args": dict(part.call.args),
                }
            }
            if part.opaque:
                piece["thoughtSignature"] = part.opaque
            parts.append(piece)
        else:
            assert isinstance(part, ToolResultPart)
            parts.append(
                {
                    "functionResponse": {
                        "id": part.result.call_id,
                        "name": part.result.name,
                        "response": dict(part.result.payload),
                    }
                }
            )
    return {"role": "model" if turn.role is Role.model else "user", "parts": parts}


def _parse_parts(raw: list[Json]) -> tuple[Part, ...]:
    parts: list[Part] = []
    for index, piece in enumerate(raw):
        call = piece.get("functionCall")
        if isinstance(call, dict):
            parts.append(
                ToolCallPart(
                    call=ToolCall(
                        id=call.get("id") or f"call_{index}",
                        name=call["name"],
                        args=call.get("args") or {},
                    ),
                    opaque=piece.get("thoughtSignature"),
                )
            )
        elif "text" in piece:
            parts.append(
                TextPart(
                    text=piece["text"],
                    thought=bool(piece.get("thought")),
                    opaque=piece.get("thoughtSignature"),
                )
            )
    if not parts:
        raise LlmError(f"gemini candidate carried no text or tool call: {raw}")
    return tuple(parts)


def _is_call(part: Part) -> bool:
    return isinstance(part, ToolCallPart)


def _finish(reason: str | None, *, has_calls: bool) -> Finish:
    match reason:
        case "MAX_TOKENS":
            return Finish.length
        case "SAFETY" | "RECITATION" | "BLOCKLIST" | "PROHIBITED_CONTENT" | "SPII":
            return Finish.blocked
        case "MALFORMED_FUNCTION_CALL" | "MISSING_THOUGHT_SIGNATURE" | "TOO_MANY_TOOL_CALLS":
            return Finish.error
        case _:
            return Finish.tool_calls if has_calls else Finish.stop


def _usage(payload: Json) -> Usage:
    usage: dict[str, Any] = payload.get("usageMetadata") or {}
    return Usage(
        input_tokens=int(usage.get("promptTokenCount", 0)),
        output_tokens=int(usage.get("candidatesTokenCount", 0))
        + int(usage.get("thoughtsTokenCount", 0)),
        cached_input_tokens=int(usage.get("cachedContentTokenCount", 0)),
    )
