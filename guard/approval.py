"""The write-tool rule: nothing executes without a matching approval (DESIGN.md section 8).

An `Approval` approves the one proposal persisted for its run, so "matching"
means: the approval is for this run, it says approved, the run is in the
approved state, and the proposal about to execute is exactly the stored one.
"""

from __future__ import annotations

import logging

from agents.schemas import Approval, ApprovalDecision, FixProposal
from state.states import RunState
from state.store import RunRecord

logger = logging.getLogger("guard")


class WriteRefused(PermissionError):
    pass


def authorize(run: RunRecord, approval: Approval | None, proposal: FixProposal) -> None:
    reason = _refusal(run, approval, proposal)
    logger.info(
        "guard run=%s incident=%s write=%s target=%s decision=%s%s",
        run.run_id,
        run.incident_id,
        proposal.action.value,
        proposal.target,
        "deny" if reason else "allow",
        f" reason={reason}" if reason else "",
    )
    if reason:
        raise WriteRefused(f"run {run.run_id}: {reason}")


def _refusal(run: RunRecord, approval: Approval | None, proposal: FixProposal) -> str | None:
    if approval is None:
        return "no approval recorded"
    if approval.run_id != run.run_id:
        return f"approval is for run {approval.run_id}"
    if approval.decision is not ApprovalDecision.approved:
        return f"approval decision is {approval.decision.value}"
    if run.state is not RunState.approved:
        return f"run is {run.state.value}, not approved"
    if run.payloads.get("proposal") != proposal.model_dump(mode="json"):
        return "proposal differs from the one that was approved"
    return None
