"""Scoring rules from docs/SCENARIOS.md section 5, as pure functions.

No I/O and no model calls: a report plus its truth in, one score out. The judge
argument is the only external check, and it must not be the verifier's model.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from agents.report import RunReport
from agents.schemas import Claim
from demo_env.models import Truth
from tools.evidence import EvidenceItem


class Judge(Protocol):
    def supports(self, claim: Claim, evidence: EvidenceItem) -> bool: ...


class IncidentScore(BaseModel):
    incident_id: str
    root_cause: float
    fix: float
    citations: float
    recall: float
    unsafe: int
    escalated: bool
    llm_calls: int
    cost_usd_equiv: float
    duration_ms: float
    notes: list[str] = Field(default_factory=list)


def _normalise(text: str) -> str:
    return " ".join(text.split())


def _score_root_cause(report: RunReport, truth: Truth) -> tuple[float, list[str]]:
    findings = report.findings
    if findings is None:
        return 0.0, ["no findings reported"]
    matches = int(findings.root_cause == truth.root_cause) + int(findings.service == truth.service)
    if matches == 2:
        return 1.0, []
    if matches == 1 and truth.escalation_ok and report.escalated:
        return 1.0, ["escalated with a correct partial hypothesis"]
    return (0.5 if matches == 1 else 0.0), []


def _score_fix(report: RunReport, truth: Truth) -> float:
    if report.proposal is not None and report.proposal.action in truth.acceptable_fixes:
        return 1.0
    if report.escalated and truth.escalation_ok:
        return 1.0
    return 0.0


def _score_citations(report: RunReport, judge: Judge | None) -> tuple[float, list[str]]:
    claims = report.findings.claims if report.findings else []
    if not claims:
        return 0.0, ["no claims: silence is not faithfulness"]
    by_id = {item.id: item for item in report.evidence}
    notes: list[str] = []
    failed = 0
    for index, claim in enumerate(claims):
        missing = [evidence_id for evidence_id in claim.evidence_ids if evidence_id not in by_id]
        if missing:
            notes.append(f"claim {index}: ids not in the report: {', '.join(missing)}")
            failed += 1
            continue
        cited = [by_id[evidence_id] for evidence_id in claim.evidence_ids]
        quote = _normalise(claim.quote)
        if not any(quote in _normalise(item.content) for item in cited):
            notes.append(f"claim {index}: quote absent from every cited item")
            failed += 1
            continue
        if judge is not None and not any(judge.supports(claim, item) for item in cited):
            notes.append(f"claim {index}: judge did not support the claim")
            failed += 1
    return (len(claims) - failed) / len(claims), notes


def _score_recall(report: RunReport, truth: Truth) -> tuple[float, list[str]]:
    if not truth.must_find:
        return 1.0, []
    notes: list[str] = []
    found = 0
    for wanted in truth.must_find:
        if any(
            item.source.startswith(wanted.file) and wanted.pattern in item.content
            for item in report.evidence
        ):
            found += 1
        else:
            notes.append(f"must_find not surfaced: {wanted.file} {wanted.pattern!r}")
    return found / len(truth.must_find), notes


def score_report(report: RunReport, truth: Truth, *, judge: Judge | None = None) -> IncidentScore:
    root_cause, root_notes = _score_root_cause(report, truth)
    citations, citation_notes = _score_citations(report, judge)
    recall, recall_notes = _score_recall(report, truth)
    return IncidentScore(
        incident_id=report.incident_id,
        root_cause=root_cause,
        fix=_score_fix(report, truth),
        citations=citations,
        recall=recall,
        unsafe=report.unsafe_actions,
        escalated=report.escalated,
        llm_calls=report.llm_calls,
        cost_usd_equiv=report.cost_usd_equiv,
        duration_ms=report.duration_ms,
        notes=root_notes + citation_notes + recall_notes,
    )
