"""Triage then diagnosis through ADK on S01, with scripted model replies and no network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.pipeline import ReactRunner
from demo_env.load import INCIDENTS_DIR, load_incident
from evals.scoring import score_report
from llm.ledger import Ledger
from state.states import RunState
from tests.support import StubTransport, settings_for

S01 = load_incident(INCIDENTS_DIR / "S01_bad_deploy_env_var")

TRIAGE = {
    "service": "checkout-api",
    "severity": "sev2",
    "areas_to_check": ["recent deploys", "error logs"],
    "known_pattern": False,
}


def _tool(name: str, args: dict, call_id: str) -> dict:
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


def _findings(evidence_id: str) -> dict:
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


def _run(tmp_path: Path, *replies: dict) -> tuple[object, StubTransport]:
    transport = StubTransport(*replies)
    ledger = Ledger(tmp_path / "ledger.db")
    try:
        runner = ReactRunner(
            settings_for(chain=("openrouter",)), ledger=ledger, transport=transport
        )
        return runner.run(S01), transport
    finally:
        ledger.close()


def test_s01_runs_from_alert_to_scored_findings(tmp_path: Path) -> None:
    report, transport = _run(
        tmp_path,
        _tool("submit_triage", TRIAGE, "t1"),
        _tool("list_recent_deploys", {"service": "checkout-api"}, "d1"),
        _tool("submit_findings", _findings("ev_deploy_1"), "d2"),
    )

    assert report.state is RunState.diagnosed
    assert report.findings is not None
    assert [item.id for item in report.evidence] == ["ev_deploy_1"]
    assert report.llm_calls == len(transport.requests) == 3
    assert score_report(report, S01.truth).root_cause == 1.0


def test_citing_an_id_that_does_not_exist_is_sent_back_then_fails(tmp_path: Path) -> None:
    report, transport = _run(
        tmp_path,
        _tool("submit_triage", TRIAGE, "t1"),
        _tool("submit_findings", _findings("ev_log_9"), "d1"),
        _tool("submit_findings", _findings("ev_log_9"), "d2"),
    )

    retry_request = json.dumps(transport.requests[2].body)
    assert "cites ids that do not exist: ev_log_9" in retry_request
    assert report.state is RunState.failed
    assert report.findings is None


def test_a_diagnosis_that_never_submits_escalates_at_the_step_cap(tmp_path: Path) -> None:
    looping = [_tool("list_recent_deploys", {"service": "checkout-api"}, f"d{n}") for n in range(6)]
    report, transport = _run(tmp_path, _tool("submit_triage", TRIAGE, "t1"), *looping)

    assert report.state is RunState.escalated
    assert report.stop_reason == "react step cap hit"
    assert len(transport.requests) == 7


@pytest.mark.parametrize("bad_service", ["payments-db"])
def test_triage_naming_an_unknown_service_is_rejected(tmp_path: Path, bad_service: str) -> None:
    report, transport = _run(
        tmp_path,
        _tool("submit_triage", {**TRIAGE, "service": bad_service}, "t1"),
        _tool("submit_triage", {**TRIAGE, "service": bad_service}, "t2"),
    )

    assert f"service '{bad_service}' is not one of" in json.dumps(transport.requests[1].body)
    assert report.state is RunState.failed
