"""T03: which backends can actually do the three things the agents need?

A table, one row per backend, three checks: plain text, a tool call with its
result fed back, and schema-shaped output through a submit tool. That third
check is the mechanism every agent will use for structured output, so it is
tested before any agent exists.

This is the only place a model is called outside a run, and it is never part of
`make test`. Run it by hand with `uv run python tasks.py smoke`.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from agents.schemas import Triage
from config import REPO_ROOT, Mode, Settings, load_settings
from llm.client import LlmClient
from llm.errors import LlmError
from llm.ledger import LEDGER_PATH, Ledger
from llm.transport import HttpxTransport, Transport
from llm.turn import (
    Finish,
    ModelCall,
    Role,
    TextPart,
    ToolResult,
    ToolResultPart,
    ToolSpec,
    Turn,
)

RESULTS_DIR = REPO_ROOT / "evals" / "results"

# Room for reasoning models to think before they answer; a tighter cap measures
# the cap, not whether the model can call a tool.
MAX_OUTPUT_TOKENS = 1024

NOTE_TOOL = ToolSpec(
    name="record_note",
    description="Record a short note. Call this whenever asked to record something.",
    parameters={
        "type": "object",
        "properties": {"note": {"type": "string", "description": "The note text."}},
        "required": ["note"],
    },
)

SUBMIT_TOOL = ToolSpec(
    name="submit_triage",
    description="Submit the triage result. This is the only way to answer.",
    parameters=Triage.model_json_schema(),
)


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class BackendResult:
    backend: str
    model: str
    checks: tuple[Check, ...]
    skipped: str = ""

    @property
    def passed(self) -> bool:
        return not self.skipped and all(check.passed for check in self.checks)


def run_smoke(
    *,
    backends: Sequence[str] | None = None,
    write: bool = False,
    transport_factory: Callable[[str], Transport] | None = None,
    out_dir: Path | None = None,
    ledger_path: Path = LEDGER_PATH,
) -> int:
    settings = load_settings()
    names = list(backends or settings.llm.chain)
    results = [_check_backend(settings, name, transport_factory, ledger_path) for name in names]
    _print_table(results)
    _print_recommendation(settings, results)
    if write:
        _write(results, out_dir or RESULTS_DIR)
    configured = [result for result in results if not result.skipped]
    return 0 if configured and all(result.passed for result in configured) else 1


def _check_backend(
    settings: Settings,
    name: str,
    transport_factory: Callable[[str], Transport] | None,
    ledger_path: Path,
) -> BackendResult:
    config = settings.backend(name)
    if not config.is_configured():
        return BackendResult(
            backend=name,
            model=config.model,
            checks=(),
            skipped=f"{config.api_key_env} is not set",
        )
    single = _only(settings, name)
    ledger = Ledger(ledger_path)
    client = LlmClient(
        single,
        run_id=f"smoke-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}",
        incident_id="smoke",
        ledger=ledger,
        transport=transport_factory(name) if transport_factory else HttpxTransport(),
    )
    try:
        return BackendResult(
            backend=name,
            model=config.model,
            checks=(
                _hello(client),
                _tool_round_trip(client),
                _structured(client),
            ),
        )
    finally:
        client.close()


def _hello(client: LlmClient) -> Check:
    call = ModelCall(
        agent="smoke",
        system="You are a smoke test. Answer with the single word ready.",
        turns=(Turn(Role.user, (TextPart("Say ready."),)),),
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )
    try:
        reply = client.complete(call).reply
    except LlmError as exc:
        return Check("hello", False, _one_line(exc))
    passed = "ready" in reply.text.lower()
    return Check("hello", passed, _one_line(reply.text) or "empty reply")


def _tool_round_trip(client: LlmClient) -> Check:
    first = ModelCall(
        agent="smoke",
        system="You are a smoke test. Follow the instruction exactly.",
        turns=(Turn(Role.user, (TextPart("Call record_note with note set to ping."),)),),
        tools=(NOTE_TOOL,),
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )
    try:
        reply = client.complete(first).reply
    except LlmError as exc:
        return Check("tool_call", False, _one_line(exc))
    call = next((item for item in reply.tool_calls if item.name == NOTE_TOOL.name), None)
    if call is None:
        return Check("tool_call", False, f"no record_note call in: {_one_line(reply.text)}")
    second = ModelCall(
        agent="smoke",
        system="You are a smoke test. Follow the instruction exactly.",
        turns=(
            first.turns[0],
            Turn(Role.model, reply.parts),
            Turn(
                Role.user,
                (ToolResultPart(ToolResult(call.id, call.name, {"recorded": "true"})),),
            ),
        ),
        tools=(NOTE_TOOL,),
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )
    try:
        after = client.complete(second).reply
    except LlmError as exc:
        return Check("tool_call", False, _one_line(exc))
    passed = after.finish is Finish.stop and bool(after.text.strip())
    return Check("tool_call", passed, f"result accepted, reply: {_one_line(after.text)}")


def _structured(client: LlmClient) -> Check:
    call = ModelCall(
        agent="smoke",
        system="You are a smoke test. Answer only by calling submit_triage.",
        turns=(
            Turn(
                Role.user,
                (
                    TextPart(
                        "Alert: checkout-api returns 500s since 09:10 after a deploy. "
                        "Triage it by calling submit_triage."
                    ),
                ),
            ),
        ),
        tools=(SUBMIT_TOOL,),
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )
    try:
        reply = client.complete(call).reply
    except LlmError as exc:
        return Check("structured", False, _one_line(exc))
    submitted = next((item for item in reply.tool_calls if item.name == SUBMIT_TOOL.name), None)
    if submitted is None:
        return Check("structured", False, f"no submit_triage call in: {_one_line(reply.text)}")
    try:
        parsed = Triage.model_validate(dict(submitted.args))
    except ValueError as exc:
        return Check("structured", False, f"args did not validate: {_one_line(exc)}")
    return Check("structured", True, f"{parsed.service}/{parsed.severity.value}")


def _only(settings: Settings, name: str) -> Settings:
    """One model per row, always live.

    No chain fallback and no in-backend fallback model, so a row reports only the
    model it names. Record mode skips the cache read: the cache is deliberately
    blind to the model, so a reply recorded from another model would otherwise
    pass this one.
    """
    single = settings.backend(name).model_copy(update={"fallback_models": []})
    llm = settings.llm.model_copy(
        update={
            "mode": Mode.record,
            "chain": [name],
            "daily_budget": {name: settings.llm.daily_budget.get(name)},
            "backends": {**settings.llm.backends, name: single},
        }
    )
    return settings.model_copy(update={"llm": llm})


def _print_table(results: Sequence[BackendResult]) -> None:
    print(f"{'backend':<12} {'hello':<8} {'tool_call':<10} {'structured':<11} note")
    for result in results:
        if result.skipped:
            print(f"{result.backend:<12} {'skip':<8} {'skip':<10} {'skip':<11} {result.skipped}")
            continue
        cells = []
        note = result.model
        for check in result.checks:
            cells.append("ok" if check.passed else "fail")
            if not check.passed:
                note = f"{check.name}: {check.detail}"
        print(f"{result.backend:<12} {cells[0]:<8} {cells[1]:<10} {cells[2]:<11} {note}")


def _print_recommendation(settings: Settings, results: Sequence[BackendResult]) -> None:
    passing = [result.backend for result in results if result.passed]
    if not passing:
        print("\nNo backend passed every check. Fix one before building agents on it.")
        return
    print(f"\nPassed every check: {', '.join(passing)}")
    gemini = next((result for result in results if result.backend == "gemini"), None)
    budget = settings.llm.daily_budget.get("gemini")
    if gemini is not None and gemini.passed and budget is not None and budget >= 250:
        print(
            f"PLAN section 4: Gemini budget is {budget}/day (>= 250), so Gemini is primary "
            "and config.yaml already matches."
        )
    else:
        print(
            "PLAN section 4: Gemini is primary only at 250 calls/day or more. Read your real "
            "quota in AI Studio, set daily_budget.gemini, and make a local model primary if it "
            "is lower."
        )


def _write(results: Sequence[BackendResult], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    path = out_dir / f"smoke-{stamp}.json"
    payload = {
        "ts": stamp,
        "rows": [
            {
                "backend": result.backend,
                "model": result.model,
                "skipped": result.skipped,
                "checks": [
                    {"name": check.name, "passed": check.passed, "detail": check.detail}
                    for check in result.checks
                ],
            }
            for result in results
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nWrote {path}")


def _one_line(value: object) -> str:
    return " ".join(str(value).split())[:120]
