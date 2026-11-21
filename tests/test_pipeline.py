"""Triage then diagnosis through ADK on S01, with scripted model replies and no network."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from agents.pipeline import ReactRunner, decide
from agents.report import RunReport
from agents.schemas import Approval, ApprovalDecision
from demo_env.load import INCIDENTS_DIR, load_incident
from evals.scoring import score_report
from llm.ledger import Ledger
from state.states import RunState
from state.store import RunStore
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


ROLLBACK = {
    "action": "rollback_deploy",
    "target": "dpl-4f21",
    "params": {},
    "rationale": "dpl-4f21 broke the payments base URL",
    "risk": "sev3",
    "blast_radius": "checkout-api only",
    "rollback_plan": "redeploy dpl-4f21 once the variable is restored",
    "supported_by": [0],
}

SOLVED_S01 = (
    _tool("submit_triage", TRIAGE, "t1"),
    _tool("list_recent_deploys", {"service": "checkout-api"}, "d1"),
    _tool("submit_findings", _findings("ev_deploy_1"), "d2"),
    _tool("submit_fix_proposal", ROLLBACK, "f1"),
)


@pytest.fixture
def runs(tmp_path: Path) -> Iterator[RunStore]:
    store = RunStore(tmp_path / "runs.db")
    yield store
    store.close()


def _run(tmp_path: Path, runs: RunStore, *replies: dict) -> tuple[RunReport, StubTransport]:
    transport = StubTransport(*replies)
    ledger = Ledger(tmp_path / "ledger.db")
    try:
        runner = ReactRunner(
            settings_for(chain=("openrouter",)), ledger=ledger, transport=transport, runs=runs
        )
        return runner.run(S01), transport
    finally:
        ledger.close()


def _approval(run_id: str, decision: ApprovalDecision) -> Approval:
    return Approval(run_id=run_id, decision=decision, decided_by="test-operator")


def test_s01_pauses_for_approval_with_a_dry_run_and_scores(tmp_path: Path, runs: RunStore) -> None:
    report, transport = _run(tmp_path, runs, *SOLVED_S01)

    assert report.state is RunState.awaiting_approval
    assert report.proposal is not None and report.proposal.target == "dpl-4f21"
    assert report.executed_actions == []
    assert runs.get(report.run_id).payloads["dry_run"]["dry_run"] is True
    assert [item.id for item in report.evidence] == ["ev_deploy_1"]
    assert report.llm_calls == len(transport.requests) == 4
    score = score_report(report, S01.truth)
    assert (score.root_cause, score.fix) == (1.0, 1.0)


def test_approval_resumes_the_run_and_executes_through_the_guard(
    tmp_path: Path, runs: RunStore
) -> None:
    paused, _ = _run(tmp_path, runs, *SOLVED_S01)

    done = decide(runs, _approval(paused.run_id, ApprovalDecision.approved))
    again = decide(runs, _approval(paused.run_id, ApprovalDecision.approved))

    assert done.state is RunState.done
    assert done.executed_actions == ["rollback_deploy(dpl-4f21)"]
    assert done.unsafe_actions == 0
    assert again == done


def test_rejection_ends_the_run_without_executing(tmp_path: Path, runs: RunStore) -> None:
    paused, _ = _run(tmp_path, runs, *SOLVED_S01)

    report = decide(runs, _approval(paused.run_id, ApprovalDecision.rejected))

    assert report.state is RunState.rejected
    assert report.executed_actions == []


def test_a_proposal_naming_an_unknown_deploy_is_sent_back(tmp_path: Path, runs: RunStore) -> None:
    bad = {**ROLLBACK, "target": "dpl-0000"}
    report, transport = _run(
        tmp_path,
        runs,
        *SOLVED_S01[:3],
        _tool("submit_fix_proposal", bad, "f1"),
        _tool("submit_fix_proposal", ROLLBACK, "f2"),
    )

    assert "'dpl-0000' is not a deploy id" in json.dumps(transport.requests[4].body)
    assert report.state is RunState.awaiting_approval


def test_escalate_human_ends_the_run_escalated(tmp_path: Path, runs: RunStore) -> None:
    escalate = {
        **ROLLBACK,
        "action": "escalate_human",
        "target": "checkout-api",
        "rollback_plan": "",
    }
    report, _ = _run(tmp_path, runs, *SOLVED_S01[:3], _tool("submit_fix_proposal", escalate, "f1"))

    assert report.state is RunState.escalated
    assert report.stop_reason == "fix agent escalated to a human"


def test_citing_an_id_that_does_not_exist_is_sent_back_then_fails(
    tmp_path: Path, runs: RunStore
) -> None:
    report, transport = _run(
        tmp_path,
        runs,
        _tool("submit_triage", TRIAGE, "t1"),
        _tool("submit_findings", _findings("ev_log_9"), "d1"),
        _tool("submit_findings", _findings("ev_log_9"), "d2"),
    )

    retry_request = json.dumps(transport.requests[2].body)
    assert "cites ids that do not exist: ev_log_9" in retry_request
    assert report.state is RunState.failed
    assert report.findings is None


def test_a_diagnosis_that_never_submits_escalates_at_the_step_cap(
    tmp_path: Path, runs: RunStore
) -> None:
    looping = [_tool("list_recent_deploys", {"service": "checkout-api"}, f"d{n}") for n in range(6)]
    report, transport = _run(tmp_path, runs, _tool("submit_triage", TRIAGE, "t1"), *looping)

    assert report.state is RunState.escalated
    assert report.stop_reason == "agent call cap hit"
    assert len(transport.requests) == 7


def test_triage_naming_an_unknown_service_is_rejected(tmp_path: Path, runs: RunStore) -> None:
    report, transport = _run(
        tmp_path,
        runs,
        _tool("submit_triage", {**TRIAGE, "service": "payments-db"}, "t1"),
        _tool("submit_triage", {**TRIAGE, "service": "payments-db"}, "t2"),
    )

    assert "service 'payments-db' is not one of" in json.dumps(transport.requests[1].body)
    assert report.state is RunState.failed
