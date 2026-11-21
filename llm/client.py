"""The one place a model is called.

Cache, daily budget, fallback chain, the three modes and the per-call log all
live here, so no agent, tool or test ever sees a provider. `AGENTS.md` rule 1 is
this module, and `tests/test_llm.py` proves it holds for the paths that matter.

Modes, stated once:
  live    read the cache, write the cache, spend quota on a miss
  record  never read the cache, always call, overwrite the entry
  replay  read the cache only, never spend, and a miss raises ReplayMiss
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass

from config import Mode, Settings
from llm.dialects import parse as parse_reply
from llm.dialects import render as render_request
from llm.errors import LlmError, LlmUnavailable, ProviderError, QuotaExhausted, ReplayMiss
from llm.ledger import CallStatus, Ledger
from llm.transport import HttpxTransport, Transport
from llm.turn import (
    ModelCall,
    ModelReply,
    Usage,
    reply_from_json,
    reply_to_json,
    turn_to_json,
)

logger = logging.getLogger("llm")


@dataclass(frozen=True, slots=True)
class Completion:
    reply: ModelReply
    backend: str
    model: str
    cache_hit: bool
    row_id: int


def cache_key(call: ModelCall) -> str:
    """Content hash. Deliberately blind to backend and model.

    A fixture recorded against Gemini has to replay on the OpenRouter path, or a
    laptop with no Gemini key cannot run CI or the eval at all. Model choice is
    an optimisation variable, not part of the question being asked.
    """
    material = {
        "system": call.system,
        "turns": [turn_to_json(turn) for turn in call.turns],
        "tools": [
            {"name": spec.name, "description": spec.description, "parameters": spec.parameters}
            for spec in call.tools
        ],
        "temperature": call.temperature,
        "max_output_tokens": call.max_output_tokens,
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class LlmClient:
    def __init__(
        self,
        settings: Settings,
        *,
        run_id: str,
        incident_id: str,
        ledger: Ledger | None = None,
        transport: Transport | None = None,
    ) -> None:
        self.settings = settings
        self.run_id = run_id
        self.incident_id = incident_id
        self.ledger = ledger if ledger is not None else Ledger()
        self.transport: Transport = transport if transport is not None else HttpxTransport()

    def close(self) -> None:
        self.ledger.close()

    def turns(self) -> int:
        return self.ledger.turns(self.run_id)

    def complete(self, call: ModelCall) -> Completion:
        mode = self.settings.llm.mode
        key = cache_key(call)
        if mode is not Mode.record:
            hit = self._from_cache(call, key)
            if hit is not None:
                return hit
            if mode is Mode.replay:
                raise ReplayMiss(
                    key=key, chain=self.settings.llm.chain, agent=call.agent, run_id=self.run_id
                )

        attempts: list[str] = []
        blocked: dict[str, int] = {}
        blocked_limits: dict[str, int | None] = {}
        tried = False
        for backend_name in self.settings.usable_chain():
            config = self.settings.backend(backend_name)
            limit = self.settings.llm.daily_budget.get(backend_name)
            for model in [config.model, *config.fallback_models]:
                spent = self.ledger.spent_today(backend_name)
                if limit is not None and spent >= limit:
                    self.ledger.log_skipped(
                        run_id=self.run_id,
                        incident_id=self.incident_id,
                        agent=call.agent,
                        backend=backend_name,
                        model=model,
                        cache_key=key,
                        detail=f"daily budget {spent}/{limit}",
                    )
                    attempts.append(f"{backend_name}/{model}: budget {spent}/{limit}")
                    blocked[backend_name] = spent
                    blocked_limits[backend_name] = limit
                    break
                tried = True
                result = self._attempt(call, key, backend_name, model, limit)
                if result is not None:
                    return result
                attempts.append(f"{backend_name}/{model} failed; see ledger")

        if blocked and not tried:
            raise QuotaExhausted(spent=blocked, limits=blocked_limits)
        raise LlmUnavailable(attempts=attempts or ["no backend is configured"])

    def _attempt(
        self, call: ModelCall, key: str, backend_name: str, model: str, limit: int | None
    ) -> Completion | None:
        config = self.settings.backend(backend_name).model_copy(update={"model": model})
        row_id = self.ledger.reserve(
            run_id=self.run_id,
            incident_id=self.incident_id,
            agent=call.agent,
            backend=backend_name,
            model=model,
            cache_key=key,
        )
        started = time.perf_counter()
        try:
            request = render_request(call, config)
            payload = self.transport.post(request)
            reply = parse_reply(payload, config.dialect)
        except ProviderError as exc:
            self._settle_error(row_id, started, str(exc))
            if exc.retryable:
                return None
            raise LlmError(f"{backend_name}/{model} rejected the request: {exc}") from exc
        except LlmError as exc:
            self._settle_error(row_id, started, str(exc))
            raise
        latency_ms = (time.perf_counter() - started) * 1000
        cost = self._cost(model, reply.usage)
        self.ledger.settle(
            row_id,
            status=CallStatus.ok,
            tokens_in=reply.usage.input_tokens,
            tokens_out=reply.usage.output_tokens,
            latency_ms=latency_ms,
            cost_usd_equiv=cost,
            detail=f"budget {limit if limit is not None else 'unlimited'}",
        )
        if self.settings.llm.mode is not Mode.replay:
            self.ledger.put_cache(
                key, backend=backend_name, model=model, payload=reply_to_json(reply)
            )
        self._log(call, backend_name, model, CallStatus.ok, reply.usage, latency_ms, cost, False)
        return Completion(
            reply=reply, backend=backend_name, model=model, cache_hit=False, row_id=row_id
        )

    def _from_cache(self, call: ModelCall, key: str) -> Completion | None:
        cached = self.ledger.get_cache(key)
        if cached is None:
            return None
        reply = reply_from_json(cached.payload)
        cost = self._cost(cached.model, reply.usage)
        row_id = self.ledger.record(
            run_id=self.run_id,
            incident_id=self.incident_id,
            agent=call.agent,
            backend=cached.backend,
            model=cached.model,
            cache_key=key,
            status=CallStatus.hit,
            usage={
                "input_tokens": reply.usage.input_tokens,
                "output_tokens": reply.usage.output_tokens,
            },
            cost_usd_equiv=cost,
            detail=f"recorded {cached.created_at}",
        )
        self._log(call, cached.backend, cached.model, CallStatus.hit, reply.usage, 0.0, cost, True)
        return Completion(
            reply=reply, backend=cached.backend, model=cached.model, cache_hit=True, row_id=row_id
        )

    def _settle_error(self, row_id: int, started: float, detail: str) -> None:
        self.ledger.settle(
            row_id,
            status=CallStatus.error,
            latency_ms=(time.perf_counter() - started) * 1000,
            detail=detail[:500],
        )

    def _cost(self, model: str, usage: Usage) -> float:
        price = self.settings.price(model)
        return (
            usage.input_tokens * price.input_per_mtok + usage.output_tokens * price.output_per_mtok
        ) / 1_000_000

    def _log(
        self,
        call: ModelCall,
        backend: str,
        model: str,
        status: CallStatus,
        usage: Usage,
        latency_ms: float,
        cost: float,
        cache_hit: bool,
    ) -> None:
        seconds = latency_ms / 1000
        tps = usage.output_tokens / seconds if seconds > 0 else 0.0
        logger.info(
            "llm run=%s incident=%s agent=%s backend=%s model=%s status=%s in=%d out=%d "
            "latency=%.0fms tps=%.1f cost=%.8f cache_hit=%s",
            self.run_id,
            self.incident_id,
            call.agent,
            backend,
            model,
            status.value,
            usage.input_tokens,
            usage.output_tokens,
            latency_ms,
            tps,
            cost,
            cache_hit,
        )
