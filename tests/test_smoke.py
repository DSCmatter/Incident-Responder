"""The T03 smoke harness, driven offline: scripted replies in, table and JSON out."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm.smoke import run_smoke
from tests.support import S01_TRIAGE, StubTransport, openai_text, openai_tool_call


def _run(tmp_path: Path, *replies: dict) -> tuple[int, dict]:
    code = run_smoke(
        backends=["gemini", "ollama"],
        write=True,
        transport_factory=lambda _name: StubTransport(*replies),
        out_dir=tmp_path,
        ledger_path=tmp_path / "ledger.db",
    )
    (written,) = tmp_path.glob("smoke-*.json")
    return code, json.loads(written.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _no_gemini_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.delenv("INCIDENT_LLM_MODE", raising=False)


def test_a_backend_that_does_all_three_passes_and_a_keyless_one_is_skipped(
    tmp_path: Path,
) -> None:
    code, payload = _run(
        tmp_path,
        openai_text("ready"),
        openai_tool_call("record_note", {"note": "ping"}),
        openai_text("noted"),
        openai_tool_call("submit_triage", S01_TRIAGE),
    )

    rows = {row["backend"]: row for row in payload["rows"]}
    assert code == 0
    assert rows["gemini"]["skipped"] == "GEMINI_API_KEY is not set"
    assert [check["passed"] for check in rows["ollama"]["checks"]] == [True, True, True]


def test_submit_args_that_break_the_schema_fail_the_structured_check(tmp_path: Path) -> None:
    code, payload = _run(
        tmp_path,
        openai_text("ready"),
        openai_tool_call("record_note", {"note": "ping"}),
        openai_text("noted"),
        openai_tool_call("submit_triage", {**S01_TRIAGE, "severity": "sev9"}),
    )

    (ollama,) = [row for row in payload["rows"] if row["backend"] == "ollama"]
    structured = {check["name"]: check for check in ollama["checks"]}["structured"]
    assert code == 1
    assert not structured["passed"]
    assert "did not validate" in structured["detail"]


def test_a_rerun_asks_the_model_again_instead_of_trusting_the_cache(tmp_path: Path) -> None:
    script = (
        openai_text("ready"),
        openai_tool_call("record_note", {"note": "ping"}),
        openai_text("noted"),
        openai_tool_call("submit_triage", S01_TRIAGE),
    )
    transports: list[StubTransport] = []

    def factory(_name: str) -> StubTransport:
        transports.append(StubTransport(*script))
        return transports[-1]

    for _ in range(2):
        run_smoke(
            backends=["ollama"],
            transport_factory=factory,
            ledger_path=tmp_path / "ledger.db",
        )

    assert [len(transport.requests) for transport in transports] == [4, 4]
