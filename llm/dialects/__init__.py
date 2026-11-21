"""Dialect dispatch, keyed on `BackendConfig.dialect`.

A new provider means a new module and one line here, not a branch in the client.
"""

from __future__ import annotations

from typing import Literal

from config import BackendConfig
from llm.dialects import gemini as gemini_dialect
from llm.dialects import openai as openai_dialect
from llm.transport import HttpRequest
from llm.turn import Json, ModelCall, ModelReply

Dialect = Literal["gemini", "openai"]


def render(call: ModelCall, backend: BackendConfig) -> HttpRequest:
    match backend.dialect:
        case "gemini":
            return gemini_dialect.render(call, backend)
        case "openai":
            return openai_dialect.render(call, backend)
        case other:
            raise ValueError(f"unknown dialect {other!r}")


def parse(payload: Json, dialect: Dialect) -> ModelReply:
    match dialect:
        case "gemini":
            return gemini_dialect.parse(payload)
        case "openai":
            return openai_dialect.parse(payload)
        case other:
            raise ValueError(f"unknown dialect {other!r}")


__all__ = ["parse", "render"]
