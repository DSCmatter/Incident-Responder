"""Agent input and output contracts, transcribed from docs/DESIGN.md section 3.

Every model forbids unknown fields: a model that invents a field is a bug we want
to see (the caller retries once with the validation error), not silently drop.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Severity(StrEnum):
    sev1 = "sev1"  # full outage
    sev2 = "sev2"  # degraded
    sev3 = "sev3"  # minor


class RootCause(StrEnum):
    bad_deploy = "bad_deploy"
    resource_exhaustion = "resource_exhaustion"
    slow_query = "slow_query"
    dependency_failure = "dependency_failure"
    disk_full = "disk_full"
    misconfiguration = "misconfiguration"
    capacity = "capacity"
    cert_expiry = "cert_expiry"
    network_dns = "network_dns"
    unknown = "unknown"


class FixClass(StrEnum):
    rollback_deploy = "rollback_deploy"
    restart_service = "restart_service"
    config_change = "config_change"
    scale_out = "scale_out"
    add_index = "add_index"
    rotate_cert = "rotate_cert"
    free_disk = "free_disk"
    escalate_human = "escalate_human"


class Triage(Strict):
    service: str
    severity: Severity
    areas_to_check: list[str]
    known_pattern: bool


class Claim(Strict):
    text: str
    evidence_ids: list[str] = Field(min_length=1)
    quote: str


class Findings(Strict):
    root_cause: RootCause
    service: str
    summary: str
    confidence: float = Field(ge=0.0, le=1.0)
    claims: list[Claim]


class ClaimVerdict(Strict):
    claim_index: int
    supported: bool
    reason: str


class Verification(Strict):
    all_supported: bool
    verdicts: list[ClaimVerdict]


class FixProposal(Strict):
    action: FixClass
    target: str
    params: dict[str, str] = Field(default_factory=dict)
    rationale: str
    risk: Severity
    blast_radius: str
    rollback_plan: str
    supported_by: list[int]


class CriticVerdict(Strict):
    approved: bool
    issues: list[str]
    required_changes: list[str]


class ApprovalDecision(StrEnum):
    approved = "approved"
    rejected = "rejected"


class Approval(Strict):
    run_id: str
    decision: ApprovalDecision
    decided_by: str
    note: str = ""
