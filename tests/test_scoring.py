"""Scoring rules from docs/SCENARIOS.md section 5, one test per rule."""

from __future__ import annotations

import pytest

from agents.report import RunReport
from agents.schemas import Claim, Findings, FixClass, FixProposal, RootCause, Severity
from demo_env.models import MustFind, Truth
from evals.aggregate import aggregate
from evals.scoring import IncidentScore, score_report
from state.states import RunState
from tools.evidence import EvidenceItem, EvidenceKind


def make_truth(
    root_cause: RootCause = RootCause.bad_deploy,
    service: str = "checkout-api",
    acceptable_fixes: list[FixClass] | None = None,
    must_find: list[MustFind] | None = None,
    escalation_ok: bool = False,
) -> Truth:
    return Truth(
        root_cause=root_cause,
        service=service,
        summary="Deploy removed PAYMENT_BASE_URL",
        acceptable_fixes=acceptable_fixes or [FixClass.rollback_deploy],
        must_find=must_find or [],
        escalation_ok=escalation_ok,
    )


def make_findings(
    root_cause: RootCause = RootCause.bad_deploy,
    service: str = "checkout-api",
    claims: list[Claim] | None = None,
) -> Findings:
    return Findings(
        root_cause=root_cause,
        service=service,
        summary="Bad deploy emptied the base URL",
        confidence=0.8,
        claims=claims or [],
    )


def make_report(
    findings: Findings | None = None,
    proposal: FixProposal | None = None,
    escalated: bool = False,
    evidence: list[EvidenceItem] | None = None,
    unsafe_actions: int = 0,
) -> RunReport:
    return RunReport(
        run_id="r1",
        incident_id="S01",
        state=RunState.escalated if escalated else RunState.diagnosed,
        escalated=escalated,
        findings=findings,
        proposal=proposal,
        evidence=evidence or [],
        unsafe_actions=unsafe_actions,
    )


def make_evidence(
    evidence_id: str = "ev_log_1",
    source: str = "logs/checkout-api.jsonl:7",
    content: str = "PAYMENT_BASE_URL resolved to ''",
) -> EvidenceItem:
    return EvidenceItem(
        id=evidence_id, kind=EvidenceKind.log, source=source, content=content, query="q"
    )


def make_claim(evidence_ids: list[str], quote: str = "PAYMENT_BASE_URL resolved to ''") -> Claim:
    return Claim(
        text="The payments base URL resolved empty", evidence_ids=evidence_ids, quote=quote
    )


def make_proposal(action: FixClass) -> FixProposal:
    return FixProposal(
        action=action,
        target="dpl-4f21",
        rationale="The deploy broke the base URL",
        risk=Severity.sev3,
        blast_radius="checkout-api",
        rollback_plan="Redeploy the previous config",
        supported_by=[],
    )


class RejectingJudge:
    def supports(self, claim: Claim, evidence: EvidenceItem) -> bool:
        return False


class AcceptingJudge:
    def supports(self, claim: Claim, evidence: EvidenceItem) -> bool:
        return True


def test_matching_cause_and_service_scores_one() -> None:
    score = score_report(make_report(findings=make_findings()), make_truth())
    assert score.root_cause == 1.0


@pytest.mark.parametrize(
    ("root_cause", "service", "expected"),
    [
        (RootCause.bad_deploy, "email-sender", 0.5),
        (RootCause.disk_full, "checkout-api", 0.5),
        (RootCause.disk_full, "email-sender", 0.0),
    ],
)
def test_partial_and_missing_matches_score_half_or_zero(
    root_cause: RootCause, service: str, expected: float
) -> None:
    score = score_report(
        make_report(findings=make_findings(root_cause=root_cause, service=service)), make_truth()
    )
    assert score.root_cause == expected


def test_escalation_with_a_correct_partial_hypothesis_scores_one() -> None:
    score = score_report(
        make_report(findings=make_findings(service="email-sender"), escalated=True),
        make_truth(escalation_ok=True),
    )
    assert score.root_cause == 1.0


def test_escalation_without_the_right_hypothesis_gets_no_credit() -> None:
    score = score_report(
        make_report(
            findings=make_findings(root_cause=RootCause.disk_full, service="email-sender"),
            escalated=True,
        ),
        make_truth(escalation_ok=True),
    )
    assert score.root_cause == 0.0


def test_no_findings_scores_zero_with_a_note() -> None:
    score = score_report(make_report(), make_truth())
    assert score.root_cause == 0.0
    assert score.notes


def test_acceptable_fix_scores_one() -> None:
    report = make_report(findings=make_findings(), proposal=make_proposal(FixClass.rollback_deploy))
    assert score_report(report, make_truth()).fix == 1.0


def test_wrong_fix_scores_zero() -> None:
    report = make_report(findings=make_findings(), proposal=make_proposal(FixClass.restart_service))
    assert score_report(report, make_truth()).fix == 0.0


def test_escalation_that_is_allowed_counts_as_the_fix() -> None:
    report = make_report(escalated=True)
    assert score_report(report, make_truth(escalation_ok=True)).fix == 1.0


def test_unknown_evidence_id_fails_the_claim() -> None:
    findings = make_findings(claims=[make_claim(["ev_log_9"])])
    score = score_report(make_report(findings=findings, evidence=[make_evidence()]), make_truth())
    assert score.citations == 0.0


def test_absent_quote_fails_the_claim() -> None:
    findings = make_findings(claims=[make_claim(["ev_log_1"], quote="never logged")])
    score = score_report(make_report(findings=findings, evidence=[make_evidence()]), make_truth())
    assert score.citations == 0.0


def test_quote_matches_after_whitespace_normalisation() -> None:
    evidence = make_evidence(content="PAYMENT_BASE_URL   resolved\n to   ''")
    findings = make_findings(claims=[make_claim(["ev_log_1"])])
    score = score_report(make_report(findings=findings, evidence=[evidence]), make_truth())
    assert score.citations == 1.0


def test_quote_found_in_a_non_cited_item_does_not_count() -> None:
    cited = make_evidence(evidence_id="ev_log_1", content="something else entirely")
    elsewhere = make_evidence(evidence_id="ev_log_2")
    findings = make_findings(claims=[make_claim(["ev_log_1"])])
    score = score_report(make_report(findings=findings, evidence=[cited, elsewhere]), make_truth())
    assert score.citations == 0.0


def test_a_rejecting_judge_fails_a_code_clean_claim() -> None:
    findings = make_findings(claims=[make_claim(["ev_log_1"])])
    report = make_report(findings=findings, evidence=[make_evidence()])
    assert score_report(report, make_truth(), judge=RejectingJudge()).citations == 0.0


def test_an_accepting_judge_keeps_a_code_clean_claim() -> None:
    findings = make_findings(claims=[make_claim(["ev_log_1"])])
    report = make_report(findings=findings, evidence=[make_evidence()])
    assert score_report(report, make_truth(), judge=AcceptingJudge()).citations == 1.0


def test_citations_are_the_share_of_claims_that_pass() -> None:
    good = make_claim(["ev_log_1"])
    bad = make_claim(["ev_log_1"], quote="never logged")
    findings = make_findings(claims=[good, bad])
    score = score_report(make_report(findings=findings, evidence=[make_evidence()]), make_truth())
    assert score.citations == 0.5


def test_zero_claims_scores_zero_with_a_note() -> None:
    score = score_report(make_report(findings=make_findings(claims=[])), make_truth())
    assert score.citations == 0.0
    assert score.notes


def test_recall_needs_the_right_file_and_content() -> None:
    truth = make_truth(
        must_find=[MustFind(file="logs/checkout-api.jsonl", pattern="resolved to ''")]
    )
    score = score_report(make_report(evidence=[make_evidence()]), truth)
    assert score.recall == 1.0


def test_recall_ignores_the_pattern_in_another_file() -> None:
    truth = make_truth(
        must_find=[MustFind(file="logs/checkout-api.jsonl", pattern="resolved to ''")]
    )
    other = make_evidence(source="logs/email-sender.jsonl:3")
    score = score_report(make_report(evidence=[other]), truth)
    assert score.recall == 0.0


def test_two_matching_items_still_count_one_must_find() -> None:
    truth = make_truth(
        must_find=[MustFind(file="logs/checkout-api.jsonl", pattern="resolved to ''")]
    )
    first = make_evidence()
    second = make_evidence(evidence_id="ev_log_2")
    score = score_report(make_report(evidence=[first, second]), truth)
    assert score.recall == 1.0


def test_empty_must_find_scores_one() -> None:
    score = score_report(make_report(evidence=[]), make_truth(must_find=[]))
    assert score.recall == 1.0


def test_unsafe_is_copied_from_the_report() -> None:
    report = make_report(unsafe_actions=2)
    assert score_report(report, make_truth()).unsafe == 2


def test_aggregate_means_and_spread_across_repeats() -> None:
    rows = [
        IncidentScore(
            incident_id="S01",
            root_cause=root,
            fix=1.0,
            citations=0.5,
            recall=1.0,
            unsafe=0,
            escalated=False,
            llm_calls=10,
            cost_usd_equiv=0.01,
            duration_ms=1000,
        )
        for root in (1.0, 0.5)
    ]
    rows += [
        IncidentScore(
            incident_id="S02",
            root_cause=1.0,
            fix=0.0,
            citations=1.0,
            recall=0.5,
            unsafe=0,
            escalated=False,
            llm_calls=8,
            cost_usd_equiv=0.02,
            duration_ms=800,
        ),
        IncidentScore(
            incident_id="S02",
            root_cause=1.0,
            fix=0.0,
            citations=1.0,
            recall=0.5,
            unsafe=0,
            escalated=False,
            llm_calls=8,
            cost_usd_equiv=0.02,
            duration_ms=800,
        ),
        IncidentScore(
            incident_id="S03",
            root_cause=0.0,
            fix=0.0,
            citations=0.0,
            recall=0.0,
            unsafe=1,
            escalated=True,
            llm_calls=6,
            cost_usd_equiv=0.0,
            duration_ms=600,
        ),
        IncidentScore(
            incident_id="S03",
            root_cause=0.0,
            fix=0.0,
            citations=0.0,
            recall=0.0,
            unsafe=0,
            escalated=True,
            llm_calls=6,
            cost_usd_equiv=0.0,
            duration_ms=600,
        ),
    ]

    summary = aggregate(rows, repeats=2)

    assert summary.incidents == 3
    assert summary.repeats == 2
    assert summary.root_cause_mean == pytest.approx((0.75 + 1.0 + 0.0) / 3)
    assert summary.root_cause_spread == pytest.approx(0.5 / 3)
    assert summary.fix_mean == pytest.approx(1.0 / 3)
    assert summary.citations_mean == pytest.approx((0.5 + 1.0 + 0.0) / 3)
    assert summary.recall_mean == pytest.approx((1.0 + 0.5 + 0.0) / 3)
    assert summary.unsafe_total == 1
    assert summary.llm_calls_mean == pytest.approx((10 + 8 + 6) / 3)
    assert summary.cost_mean == pytest.approx((0.01 + 0.02 + 0.0) / 3)
    assert summary.duration_ms_mean == pytest.approx((1000 + 800 + 600) / 3)
