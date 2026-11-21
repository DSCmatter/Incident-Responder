"""The model boundary: one client, provider-neutral wire types, one error taxonomy."""

from llm.client import Completion, LlmClient, cache_key
from llm.errors import LlmError, LlmUnavailable, ProviderError, QuotaExhausted, ReplayMiss
from llm.ledger import CallRow, CallStatus, Ledger
from llm.turn import (
    Finish,
    ModelCall,
    ModelReply,
    TextPart,
    ToolCall,
    ToolCallPart,
    ToolResult,
    ToolResultPart,
    ToolSpec,
    Turn,
    Usage,
)

__all__ = [
    "CallRow",
    "CallStatus",
    "Completion",
    "Finish",
    "Ledger",
    "LlmClient",
    "LlmError",
    "LlmUnavailable",
    "ModelCall",
    "ModelReply",
    "ProviderError",
    "QuotaExhausted",
    "ReplayMiss",
    "TextPart",
    "ToolCall",
    "ToolCallPart",
    "ToolResult",
    "ToolResultPart",
    "ToolSpec",
    "Turn",
    "Usage",
    "cache_key",
]
