"""The error taxonomy the client, dialects and callers share.

Everything here is a subclass of `LlmError` so a caller can catch one type, and
each subtype names a different recovery. Retryable provider failures are not
errors yet: they are what the fallback chain exists for.
"""

from __future__ import annotations

from typing import ClassVar


class LlmError(RuntimeError):
    """Something the caller has to decide about: a bug, a budget, or a missing fixture."""


class ProviderError(LlmError):
    """One attempt against one backend failed.

    `retryable` is the whole fallback decision: 429, timeouts and 5xx move to the
    next backend, while a 400 means our body was wrong and no amount of falling
    through will fix it.
    """

    RETRYABLE_STATUS: ClassVar[frozenset[int]] = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

    def __init__(self, *, status: int | None, body: str, message: str = "") -> None:
        self.status = status
        self.body = body
        self.retryable = status is None or status in self.RETRYABLE_STATUS
        detail = message or (f"HTTP {status}" if status is not None else "transport failure")
        super().__init__(f"{detail}: {body[:300]}")


class ReplayMiss(LlmError):
    """Replay mode asked for a call that was never recorded."""

    def __init__(self, *, key: str, chain: list[str], agent: str, run_id: str) -> None:
        self.key = key
        super().__init__(
            f"no recorded response for {agent} in run {run_id} (key {key[:12]}). "
            f"Replay is cache-only; record it with `INCIDENT_LLM_MODE=record` over the "
            f"same chain ({', '.join(chain)}), then rerun in replay."
        )


class QuotaExhausted(LlmError):
    """Every backend in the chain is at its daily allowance."""

    def __init__(self, *, spent: dict[str, int], limits: dict[str, int | None]) -> None:
        self.spent = spent
        self.limits = limits
        detail = ", ".join(f"{name} {spent[name]}/{limits[name]}" for name in spent)
        super().__init__(f"daily budget exhausted on every backend ({detail})")


class LlmUnavailable(LlmError):
    """Every attempt failed for reasons retry and fallback could not fix."""

    def __init__(self, *, attempts: list[str]) -> None:
        self.attempts = attempts
        super().__init__("no backend answered: " + "; ".join(attempts))
