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
