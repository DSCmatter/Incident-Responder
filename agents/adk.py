"""The only module that speaks ADK's wire types.

ADK hands a model an `LlmRequest` built from `google.genai.types`, and expects
`LlmResponse` back. `ClientModel` translates both ways so every call still goes
through `LlmClient` (cache, budget, fallback chain, ledger). The tool classes
expose the evidence tools and the schema-submit tools to ADK. Nothing else in
the repo imports `google.genai`; ruff enforces that for every other file.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Callable
from typing import Any, Generic, TypeVar

from google.adk.agents import LlmAgent, RunConfig
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import InMemoryRunner
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types
from pydantic import BaseModel, ConfigDict, ValidationError

from llm.client import LlmClient
from llm.turn import (
    Finish,
    ModelCall,
    ModelReply,
    Part,
    Role,
    TextPart,
    ToolCall,
    ToolCallPart,
    ToolResult,
    ToolResultPart,
    ToolSpec,
    Turn,
)
from tools.read_only import TOOLS as READ_ONLY_TOOLS
from tools.read_only import ToolError, ToolSession, invoke_tool

_FINISH = {
    Finish.stop: types.FinishReason.STOP,
    Finish.tool_calls: types.FinishReason.STOP,
    Finish.length: types.FinishReason.MAX_TOKENS,
    Finish.blocked: types.FinishReason.SAFETY,
    Finish.error: types.FinishReason.OTHER,
}


class ClientModel(BaseLlm):
    """An ADK model whose every call is an `LlmClient.complete`."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    client: LlmClient
    agent: str
    prompt_version: str

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        reply = self.client.complete(self._call(llm_request)).reply
        yield _response(reply)

    def _call(self, request: LlmRequest) -> ModelCall:
        config = request.config or types.GenerateContentConfig()
        return ModelCall(
            agent=self.agent,
            system=_system_text(config.system_instruction),
            turns=_turns(request.contents),
            tools=_tool_specs(config.tools),
            temperature=config.temperature if config.temperature is not None else 0.0,
            max_output_tokens=config.max_output_tokens or 2048,
            prompt_version=self.prompt_version,
        )


def _system_text(instruction: types.ContentUnion | None) -> str:
    if instruction is None:
        return ""
    if isinstance(instruction, str):
        return instruction
    if isinstance(instruction, types.Content):
        return "".join(part.text or "" for part in instruction.parts or [])
    raise TypeError(f"unsupported system instruction type {type(instruction).__name__}")


def _turns(contents: list[types.Content]) -> tuple[Turn, ...]:
    """ADK content to turns, merging neighbours with the same role."""
    merged: list[tuple[Role, list[Part]]] = []
    for content in contents:
        parts = [part for raw in content.parts or [] if (part := _part(raw)) is not None]
        if not parts:
            continue
        role = Role.model if content.role == "model" else Role.user
        if merged and merged[-1][0] is role:
            merged[-1][1].extend(parts)
        else:
            merged.append((role, parts))
    return tuple(Turn(role, tuple(parts)) for role, parts in merged)


def _part(raw: types.Part) -> Part | None:
    opaque = raw.thought_signature.decode() if raw.thought_signature else None
    if raw.function_call is not None:
        call = raw.function_call
        if not call.id or not call.name:
            raise ValueError(f"function call without id or name in history: {call!r}")
        return ToolCallPart(ToolCall(call.id, call.name, dict(call.args or {})), opaque=opaque)
    if raw.function_response is not None:
        result = raw.function_response
        if not result.id or not result.name:
            raise ValueError(f"function response without id or name in history: {result!r}")
        return ToolResultPart(ToolResult(result.id, result.name, dict(result.response or {})))
    if raw.text:
        return TextPart(raw.text, thought=bool(raw.thought), opaque=opaque)
    return None


def _tool_specs(tools: list[types.Tool] | None) -> tuple[ToolSpec, ...]:
    specs: list[ToolSpec] = []
    for tool in tools or []:
        for declaration in getattr(tool, "function_declarations", None) or []:
            specs.append(
                ToolSpec(
                    name=declaration.name or "",
                    description=declaration.description or "",
                    parameters=declaration.parameters_json_schema or {"type": "object"},
                )
            )
    return tuple(specs)


def _response(reply: ModelReply) -> LlmResponse:
    usage = types.GenerateContentResponseUsageMetadata(
        prompt_token_count=reply.usage.input_tokens,
        candidates_token_count=reply.usage.output_tokens,
    )
    parts = [_genai_part(part) for part in reply.parts if not isinstance(part, ToolResultPart)]
    if not parts:
        return LlmResponse(
            error_code=_FINISH[reply.finish].value,
            error_message=f"model returned no content (finish={reply.finish.value})",
            usage_metadata=usage,
        )
    return LlmResponse(
        content=types.Content(role="model", parts=parts),
        finish_reason=_FINISH[reply.finish],
        usage_metadata=usage,
    )


def _genai_part(part: TextPart | ToolCallPart) -> types.Part:
    signature = part.opaque.encode() if part.opaque else None
    if isinstance(part, ToolCallPart):
        call = types.FunctionCall(id=part.call.id, name=part.call.name, args=dict(part.call.args))
        return types.Part(function_call=call, thought_signature=signature)
    return types.Part(text=part.text, thought=part.thought or None, thought_signature=signature)


class EvidenceTool(BaseTool):
    """A read-only tool; every result lands in the run's evidence store."""

    def __init__(self, name: str, session: ToolSession) -> None:
        spec = READ_ONLY_TOOLS[name]
        super().__init__(name=spec.name, description=spec.description)
        self._parameters = spec.parameters()
        self._session = session

    def _get_declaration(self) -> types.FunctionDeclaration:
        return types.FunctionDeclaration(
            name=self.name,
            description=self.description,
            parameters_json_schema=self._parameters,
        )

    async def run_async(self, *, args: dict[str, Any], tool_context: ToolContext) -> Any:
        try:
            return {"result": invoke_tool(self._session, self.name, json.dumps(args))}
        except ToolError as error:
            return {"error": str(error)}


Schema = TypeVar("Schema", bound=BaseModel)


class SubmitTool(BaseTool, Generic[Schema]):
    """The agent's only way to answer: arguments must parse as `schema` and pass `check`.

    A rejected submission goes back to the model with the reason, once. The
    second rejection ends the agent with no result, which the caller reports as
    FAILED (DESIGN.md section 11).
    """

    def __init__(
        self,
        name: str,
        description: str,
        schema: type[Schema],
        check: Callable[[Schema], list[str]] = lambda _value: [],
    ) -> None:
        super().__init__(name=name, description=description)
        self._schema = schema
        self._check = check
        self.result: Schema | None = None
        self.rejections: list[str] = []

    def _get_declaration(self) -> types.FunctionDeclaration:
        return types.FunctionDeclaration(
            name=self.name,
            description=self.description,
            parameters_json_schema=self._schema.model_json_schema(),
        )

    async def run_async(self, *, args: dict[str, Any], tool_context: ToolContext) -> Any:
        try:
            value = self._schema.model_validate(args)
            problems = self._check(value)
        except ValidationError as error:
            problems = [str(error)]
        if not problems:
            self.result = value
            tool_context.actions.skip_summarization = True
            return {"accepted": True}
        self.rejections.append("; ".join(problems))
        if len(self.rejections) >= 2:
            tool_context.actions.skip_summarization = True
        return {"error": "submission rejected: " + "; ".join(problems)}


async def run_agent(agent: LlmAgent, message: str, *, max_llm_calls: int) -> None:
    """One agent, one fresh session, run until it answers or hits its call cap.

    Raises ADK's `LlmCallsLimitExceededError` at the cap.
    """
    runner = InMemoryRunner(agent=agent, app_name="incident-responder")
    session = await runner.session_service.create_session(
        app_name="incident-responder", user_id="responder"
    )
    content = types.Content(role="user", parts=[types.Part(text=message)])
    async for _event in runner.run_async(
        user_id="responder",
        session_id=session.id,
        new_message=content,
        run_config=RunConfig(max_llm_calls=max_llm_calls),
    ):
        pass
    await runner.close()
