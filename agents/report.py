"""What one run hands to the eval harness: the scorer's whole input.

The scorer reads this and nothing else, so a run cannot influence its own score
through live state, logs, or a store the report does not carry.
"""

from __future__ import annotations

from pydantic import Field

from agents.schemas import (
    Approval,
    CriticVerdict,
    Findings,
    FixProposal,
    Strict,
    Verification,
)
from state.states import RunState
from tools.evidence import EvidenceItem


class RunReport(Strict):
    run_id: str
    incident_id: str
    state: RunState
    escalated: bool = False
    stop_reason: str | None = None
    findings: Findings | None = None
    verification: Verification | None = None
    proposal: FixProposal | None = None
    dry_run: str | None = None
    critic: CriticVerdict | None = None
    approval: Approval | None = None
    executed_actions: list[str] = Field(default_factory=list)
    unsafe_actions: int = 0
    evidence: list[EvidenceItem] = Field(default_factory=list)
    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd_equiv: float = 0.0
    duration_ms: float = 0.0


def render(report: RunReport) -> str:
    """The report a person reads at the terminal after `make run`."""
    lines = [
        f"Incident {report.incident_id}  run {report.run_id}",
        f"State: {report.state.value}" + (f" ({report.stop_reason})" if report.stop_reason else ""),
    ]
    if report.findings:
        findings = report.findings
        lines += [
            "",
            f"Root cause: {findings.root_cause.value} on {findings.service}"
            f" (self-reported confidence {findings.confidence:.2f})",
            f"Summary: {findings.summary}",
            "Claims:",
        ]
        for index, claim in enumerate(findings.claims):
            lines.append(f"  [{index}] {claim.text}")
            lines.append(f"      cites {', '.join(claim.evidence_ids)}: {claim.quote!r}")
    if report.proposal:
        proposal = report.proposal
        params = ", ".join(f"{key}={value}" for key, value in sorted(proposal.params.items()))
        lines += [
            "",
            f"Proposed fix: {proposal.action.value} {proposal.target}"
            + (f" ({params})" if params else ""),
            f"  risk {proposal.risk.value}; blast radius: {proposal.blast_radius}",
            f"  rollback plan: {proposal.rollback_plan or 'none'}",
            f"  rationale: {proposal.rationale}",
            f"  supported by claims {proposal.supported_by}",
        ]
    if report.dry_run:
        lines.append(f"  dry run: {report.dry_run}")
    if report.approval:
        approval = report.approval
        lines += ["", f"Decision: {approval.decision.value} by {approval.decided_by}"]
        if approval.note:
            lines.append(f"  note: {approval.note}")
    for action in report.executed_actions:
        lines.append(f"Executed: {action}")
    if report.evidence:
        lines += ["", "Evidence:"]
        lines += [f"  {item.id}  {item.source}" for item in report.evidence]
    lines += [
        "",
        f"Cost: {report.llm_calls} model calls, {report.tokens_in} tokens in,"
        f" {report.tokens_out} out, ${report.cost_usd_equiv:.6f} equivalent,"
        f" {report.duration_ms / 1000:.1f} s",
    ]
    return "\n".join(lines)
