"""The supervisor on S01 through ADK, with scripted model replies and no network."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from agents.report import RunReport
from agents.schemas import Approval, ApprovalDecision
from agents.supervisor import Supervisor, decide
from demo_env.load import INCIDENTS_DIR, load_incident
from evals.scoring import score_report
from llm.ledger import Ledger
from state.states import RunState
from state.store import RunStore
from tests.support import (
    S01_ROLLBACK,
    S01_SOLVED,
    S01_TRIAGE,
    StubTransport,
    openai_tool_call,
    s01_findings,
    settings_for,
)

S01 = load_incident(INCIDENTS_DIR / "S01_bad_deploy_env_var")


@pytest.fixture
def runs(tmp_path: Path) -> Iterator[RunStore]:
    store = RunStore(tmp_path / "runs.db")
    yield store
    store.close()


def _run(tmp_path: Path, runs: RunStore, *replies: dict) -> tuple[RunReport, StubTransport]:
    transport = StubTransport(*replies)
    ledger = Ledger(tmp_path / "ledger.db")
    try:
        runner = Supervisor(
            settings_for(chain=("openrouter",)), ledger=ledger, transport=transport, runs=runs
        )
        return runner.run(S01), transport
    finally:
        ledger.close()


def _approval(run_id: str, decision: ApprovalDecision) -> Approval:
    return Approval(run_id=run_id, decision=decision, decided_by="test-operator")


def test_s01_pauses_for_approval_with_a_dry_run_and_scores(tmp_path: Path, runs: RunStore) -> None:
    report, transport = _run(tmp_path, runs, *S01_SOLVED)

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
    paused, _ = _run(tmp_path, runs, *S01_SOLVED)

    done = decide(runs, _approval(paused.run_id, ApprovalDecision.approved))
    again = decide(runs, _approval(paused.run_id, ApprovalDecision.approved))

    assert done.state is RunState.done
    assert done.executed_actions == ["rollback_deploy(dpl-4f21)"]
    assert done.unsafe_actions == 0
    assert again == done


def test_rejection_ends_the_run_without_executing(tmp_path: Path, runs: RunStore) -> None:
    paused, _ = _run(tmp_path, runs, *S01_SOLVED)

    report = decide(runs, _approval(paused.run_id, ApprovalDecision.rejected))

    assert report.state is RunState.rejected
    assert report.executed_actions == []


def test_a_proposal_naming_an_unknown_deploy_is_sent_back(tmp_path: Path, runs: RunStore) -> None:
    bad = {**S01_ROLLBACK, "target": "dpl-0000"}
    report, transport = _run(
        tmp_path,
        runs,
        *S01_SOLVED[:3],
        openai_tool_call("submit_fix_proposal", bad, "f1"),
        openai_tool_call("submit_fix_proposal", S01_ROLLBACK, "f2"),
    )

    assert "'dpl-0000' is not a deploy id" in json.dumps(transport.requests[4].body)
    assert report.state is RunState.awaiting_approval


def test_escalate_human_ends_the_run_escalated(tmp_path: Path, runs: RunStore) -> None:
    escalate = {
        **S01_ROLLBACK,
        "action": "escalate_human",
        "target": "checkout-api",
        "rollback_plan": "",
    }
    report, _ = _run(
        tmp_path, runs, *S01_SOLVED[:3], openai_tool_call("submit_fix_proposal", escalate, "f1")
    )

    assert report.state is RunState.escalated
    assert report.stop_reason == "fix agent escalated to a human"


def test_citing_an_id_that_does_not_exist_is_sent_back_then_fails(
    tmp_path: Path, runs: RunStore
) -> None:
    report, transport = _run(
        tmp_path,
        runs,
        openai_tool_call("submit_triage", S01_TRIAGE, "t1"),
        openai_tool_call("submit_findings", s01_findings("ev_log_9"), "d1"),
        openai_tool_call("submit_findings", s01_findings("ev_log_9"), "d2"),
    )

    retry_request = json.dumps(transport.requests[2].body)
    assert "cites ids that do not exist: ev_log_9" in retry_request
    assert report.state is RunState.failed
    assert report.findings is None


def test_a_diagnosis_that_never_submits_escalates_at_the_step_cap(
    tmp_path: Path, runs: RunStore
) -> None:
    looping = [
        openai_tool_call("list_recent_deploys", {"service": "checkout-api"}, f"d{n}")
        for n in range(6)
    ]
    report, transport = _run(
        tmp_path, runs, openai_tool_call("submit_triage", S01_TRIAGE, "t1"), *looping
    )

    assert report.state is RunState.escalated
    assert report.stop_reason == "agent call cap hit"
    assert len(transport.requests) == 7


def test_triage_naming_an_unknown_service_is_rejected(tmp_path: Path, runs: RunStore) -> None:
    report, transport = _run(
        tmp_path,
        runs,
        openai_tool_call("submit_triage", {**S01_TRIAGE, "service": "payments-db"}, "t1"),
        openai_tool_call("submit_triage", {**S01_TRIAGE, "service": "payments-db"}, "t2"),
    )

    assert "service 'payments-db' is not one of" in json.dumps(transport.requests[1].body)
    assert report.state is RunState.failed
