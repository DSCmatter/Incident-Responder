"""No write executes without a matching approval, and the run state machine enforces the path."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agents.schemas import Approval, ApprovalDecision, FixProposal
from demo_env.load import INCIDENTS_DIR, load_incident
from guard.approval import WriteRefused
from state.states import RunState
from state.store import IllegalTransition, RunStore
from tools.evidence import EvidenceItem, EvidenceKind
from tools.write import dry_run, execute, proposal_problems

S01 = load_incident(INCIDENTS_DIR / "S01_bad_deploy_env_var")

PROPOSAL = FixProposal(
    action="rollback_deploy",
    target="dpl-4f21",
    rationale="deploy broke config",
    risk="sev3",
    blast_radius="checkout-api",
    rollback_plan="redeploy",
    supported_by=[0],
)


@pytest.fixture
def runs(tmp_path: Path) -> Iterator[RunStore]:
    store = RunStore(tmp_path / "runs.db")
    yield store
    store.close()


def _awaiting(runs: RunStore, run_id: str = "run-1") -> None:
    runs.create(run_id, "S01")
    for state in (RunState.triaged, RunState.diagnosed):
        runs.advance(run_id, state)
    runs.advance(
        run_id, RunState.fix_proposed, payloads={"proposal": PROPOSAL.model_dump(mode="json")}
    )
    runs.advance(run_id, RunState.awaiting_approval)


def _approve(runs: RunStore, run_id: str = "run-1") -> Approval:
    approval = Approval(run_id=run_id, decision=ApprovalDecision.approved, decided_by="operator")
    runs.record_approval(approval)
    runs.advance(run_id, RunState.approved)
    return approval


def test_an_unapproved_write_is_refused(runs: RunStore) -> None:
    _awaiting(runs)

    with pytest.raises(WriteRefused, match="no approval recorded"):
        execute(runs.get("run-1"), None, PROPOSAL)


def test_an_approval_for_another_run_is_refused(runs: RunStore) -> None:
    _awaiting(runs, "run-1")
    _awaiting(runs, "run-2")
    other = _approve(runs, "run-2")

    with pytest.raises(WriteRefused, match="approval is for run run-2"):
        execute(runs.get("run-1"), other, PROPOSAL)


def test_a_recorded_approval_does_not_count_until_the_run_is_approved(runs: RunStore) -> None:
    _awaiting(runs)
    approval = Approval(run_id="run-1", decision=ApprovalDecision.approved, decided_by="op")
    runs.record_approval(approval)

    with pytest.raises(WriteRefused, match="run is awaiting_approval"):
        execute(runs.get("run-1"), approval, PROPOSAL)


def test_a_proposal_changed_after_approval_is_refused(runs: RunStore) -> None:
    _awaiting(runs)
    approval = _approve(runs)
    swapped = PROPOSAL.model_copy(update={"target": "dpl-9999"})

    with pytest.raises(WriteRefused, match="differs from the one that was approved"):
        execute(runs.get("run-1"), approval, swapped)


def test_the_approved_proposal_executes_on_the_demo_stack(runs: RunStore) -> None:
    _awaiting(runs)
    approval = _approve(runs)

    record = execute(runs.get("run-1"), approval, PROPOSAL)

    assert record.dry_run is False
    assert record.tool == "rollback_deploy"
    assert dry_run(PROPOSAL).dry_run is True


def test_a_run_cannot_skip_approval(runs: RunStore) -> None:
    _awaiting(runs)

    with pytest.raises(IllegalTransition):
        runs.advance("run-1", RunState.executed)


def test_a_paused_run_survives_reopening_the_store(tmp_path: Path) -> None:
    first = RunStore(tmp_path / "runs.db")
    _awaiting(first)
    first.save_evidence(
        "run-1",
        [EvidenceItem(id="ev_log_1", kind=EvidenceKind.log, source="s", content="c", query="q")],
    )
    first.close()

    reopened = RunStore(tmp_path / "runs.db")
    try:
        run = reopened.get("run-1")
        assert run.state is RunState.awaiting_approval
        assert FixProposal.model_validate(run.payloads["proposal"]) == PROPOSAL
        assert [item.id for item in reopened.evidence("run-1")] == ["ev_log_1"]
    finally:
        reopened.close()


def test_a_second_different_decision_is_refused(runs: RunStore) -> None:
    _awaiting(runs)
    _approve(runs)

    with pytest.raises(IllegalTransition, match="already has a decision"):
        runs.record_approval(
            Approval(run_id="run-1", decision=ApprovalDecision.rejected, decided_by="op")
        )


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"action": "scale_out", "target": "checkout-api"}, "takes params ['replicas']"),
        ({"action": "restart_service", "target": "billing"}, "'billing' is not a service"),
        ({"rollback_plan": " "}, "rollback_plan is required"),
    ],
)
def test_proposals_that_could_not_run_are_explained(change: dict, problem: str) -> None:
    proposal = FixProposal.model_validate({**PROPOSAL.model_dump(), **change})

    assert any(problem in text for text in proposal_problems(proposal, S01))
