"""The provider-neutral wire: one request shape, one reply shape.

Both dialects render from `ModelCall` and parse into `ModelReply`, so the cache,
the budget and the tests never see a provider payload. The invariants sit in
`Turn.__post_init__` rather than in prose, because a recorded fixture that
breaks them has to fail at load instead of halfway through a run.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypeAlias

Json: TypeAlias = dict[str, Any]


class Role(StrEnum):
    user = "user"
    model = "model"


@dataclass(frozen=True, slots=True)
class TextPart:
    text: str
    thought: bool = False
    opaque: str | None = None


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    args: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ToolCallPart:
    call: ToolCall
    opaque: str | None = None


@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    name: str
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ToolResultPart:
    result: ToolResult


Part: TypeAlias = TextPart | ToolCallPart | ToolResultPart


@dataclass(frozen=True, slots=True)
class Turn:
    role: Role
    parts: tuple[Part, ...]

    def __post_init__(self) -> None:
        if not self.parts:
            raise ValueError("a turn with no parts is not a message")
        if self.role is Role.model and any(isinstance(part, ToolResultPart) for part in self.parts):
            raise ValueError("tool results belong to the user turn")
        if self.role is Role.user and any(isinstance(part, ToolCallPart) for part in self.parts):
            raise ValueError("tool calls belong to the model turn")
        for part in self.parts:
            if isinstance(part, ToolCallPart) and not part.call.id:
                raise ValueError("every tool call needs an id; dialects pair results by it")

    @property
    def text(self) -> str:
        return "".join(part.text for part in self.parts if isinstance(part, TextPart))


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    parameters: Json


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0


class Finish(StrEnum):
    stop = "stop"
    tool_calls = "tool_calls"
    length = "length"
    blocked = "blocked"
    error = "error"


@dataclass(frozen=True, slots=True)
class ModelReply:
    parts: tuple[Part, ...]
    finish: Finish
    usage: Usage

    @property
    def text(self) -> str:
        return "".join(part.text for part in self.parts if isinstance(part, TextPart))

    @property
    def tool_calls(self) -> tuple[ToolCall, ...]:
        return tuple(part.call for part in self.parts if isinstance(part, ToolCallPart))


@dataclass(frozen=True, slots=True)
class ModelCall:
    """One request to whichever backend answers first."""

    agent: str
    system: str
    turns: tuple[Turn, ...]
    tools: tuple[ToolSpec, ...] = ()
    temperature: float = 0.0
    max_output_tokens: int = 2048
    prompt_version: str = ""


def turn_to_json(turn: Turn) -> Json:
    return {"role": turn.role.value, "parts": [_part_to_json(part) for part in turn.parts]}


def reply_to_json(reply: ModelReply) -> Json:
    return {
        "parts": [_part_to_json(part) for part in reply.parts],
        "finish": reply.finish.value,
        "usage": {
            "input_tokens": reply.usage.input_tokens,
            "output_tokens": reply.usage.output_tokens,
            "cached_input_tokens": reply.usage.cached_input_tokens,
        },
    }


def reply_from_json(payload: Mapping[str, Any]) -> ModelReply:
    usage = payload["usage"]
    return ModelReply(
        parts=tuple(_part_from_json(part) for part in payload["parts"]),
        finish=Finish(payload["finish"]),
        usage=Usage(
            input_tokens=int(usage["input_tokens"]),
            output_tokens=int(usage["output_tokens"]),
            cached_input_tokens=int(usage.get("cached_input_tokens", 0)),
        ),
    )


def _part_to_json(part: Part) -> Json:
    if isinstance(part, TextPart):
        return {"type": "text", "text": part.text, "thought": part.thought, "opaque": part.opaque}
    if isinstance(part, ToolCallPart):
        call = part.call
        return {
            "type": "tool_call",
            "id": call.id,
            "name": call.name,
            "args": dict(call.args),
            "opaque": part.opaque,
        }
    result = part.result
    return {
        "type": "tool_result",
        "call_id": result.call_id,
        "name": result.name,
        "payload": dict(result.payload),
    }


def _part_from_json(payload: Mapping[str, Any]) -> Part:
    kind = payload["type"]
    if kind == "text":
        return TextPart(
            text=payload["text"], thought=bool(payload["thought"]), opaque=payload["opaque"]
        )
    if kind == "tool_call":
        call = ToolCall(id=payload["id"], name=payload["name"], args=payload["args"])
        return ToolCallPart(call=call, opaque=payload["opaque"])
    if kind == "tool_result":
        result = ToolResult(
            call_id=payload["call_id"], name=payload["name"], payload=payload["payload"]
        )
        return ToolResultPart(result=result)
    raise ValueError(f"unknown part type in a cached reply: {kind!r}")
