"""Shared test doubles: a settings factory and transports that answer from a list.

Kept out of conftest so a test can import exactly what it uses, and so the smoke
harness test can drive the same scripted transport the client tests use.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from config import (
    BackendConfig,
    Limits,
    LlmSettings,
    Mode,
    ModelPrice,
    RagSettings,
    Routing,
    Settings,
)
from llm.client import LlmClient
from llm.ledger import Ledger
from llm.transport import HttpRequest
from llm.turn import ModelCall, Role, TextPart, Turn

GEMINI_REPLY = {
    "candidates": [
        {
            "content": {"role": "model", "parts": [{"text": "deploy removed the env var"}]},
            "finishReason": "STOP",
        }
    ],
    "usageMetadata": {"promptTokenCount": 1000, "candidatesTokenCount": 500},
}

OPENAI_REPLY = {
    "choices": [
        {
            "message": {"role": "assistant", "content": "deploy removed the env var"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
}


class StubTransport:
    def __init__(self, *replies: dict | Exception) -> None:
        self.replies: list[dict | Exception] = list(replies)
        self.requests: list[HttpRequest] = []

    def post(self, request: HttpRequest) -> dict:
        self.requests.append(request)
        if not self.replies:
            raise AssertionError(f"unexpected extra call to {request.url}")
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class ExplodingTransport:
    def post(self, request: HttpRequest) -> dict:
        raise AssertionError(f"a replay must never call out: {request.url}")


def settings_for(
    *,
    mode: Mode = Mode.live,
    chain: Sequence[str] = ("gemini",),
    budgets: dict[str, int | None] | None = None,
    pricing: dict[str, ModelPrice] | None = None,
    fallbacks: dict[str, list[str]] | None = None,
    gemini_key_env: str | None = None,
) -> Settings:
    fallbacks = fallbacks or {}
    backends = {
        "gemini": BackendConfig(
            dialect="gemini",
            base_url="https://gemini.test/v1beta",
            model="gemini-test",
            api_key_env=gemini_key_env,
            fallback_models=fallbacks.get("gemini", []),
        ),
        "openrouter": BackendConfig(
            dialect="openai",
            base_url="https://openrouter.test/v1",
            model="or-test",
            fallback_models=fallbacks.get("openrouter", []),
        ),
    }
    return Settings(
        limits=Limits(
            max_llm_calls_per_run=12,
            max_react_steps=6,
            max_react_steps_fast_path=3,
            max_critic_rounds=2,
            run_timeout_seconds=60,
        ),
        routing=Routing(runbook_score_threshold=0.75),
        llm=LlmSettings(
            mode=mode,
            chain=list(chain),
            daily_budget=budgets or {name: None for name in chain},
            backends=backends,
            pricing=pricing or {},
        ),
        rag=RagSettings(k=5, embedding="local"),
    )


def client_for(tmp_path: Path, settings: Settings, transport: object, *, run_id: str = "run-1"):
    ledger = Ledger(tmp_path / "ledger.db")
    return LlmClient(
        settings,
        run_id=run_id,
        incident_id="S01",
        ledger=ledger,
        transport=transport,  # type: ignore[arg-type]
    )


def ask(text: str = "why is checkout down", agent: str = "triage") -> ModelCall:
    return ModelCall(agent=agent, system="be terse", turns=(Turn(Role.user, (TextPart(text),)),))


def openai_text(content: str) -> dict:
    return {
        "choices": [
            {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2},
    }


def openai_tool_call(name: str, args: dict, call_id: str = "c1") -> dict:
    call = {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": None, "tool_calls": [call]},
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }


S01_TRIAGE = {
    "service": "checkout-api",
    "severity": "sev2",
    "areas_to_check": ["recent deploys", "error logs"],
    "known_pattern": False,
}

S01_ROLLBACK = {
    "action": "rollback_deploy",
    "target": "dpl-4f21",
    "params": {},
    "rationale": "dpl-4f21 broke the payments base URL",
    "risk": "sev3",
    "blast_radius": "checkout-api only",
    "rollback_plan": "redeploy dpl-4f21 once the variable is restored",
    "supported_by": [0],
}


def s01_findings(evidence_id: str) -> dict:
    return {
        "root_cause": "bad_deploy",
        "service": "checkout-api",
        "summary": "dpl-4f21 broke the payments base URL",
        "confidence": 0.8,
        "claims": [
            {
                "text": "A deploy to checkout-api shortly before the alert",
                "evidence_ids": [evidence_id],
                "quote": "dpl-4f21",
            }
        ],
    }


S01_SOLVED = (
    openai_tool_call("submit_triage", S01_TRIAGE, "t1"),
    openai_tool_call("list_recent_deploys", {"service": "checkout-api"}, "d1"),
    openai_tool_call("submit_findings", s01_findings("ev_deploy_1"), "d2"),
    openai_tool_call("submit_fix_proposal", S01_ROLLBACK, "f1"),
)
