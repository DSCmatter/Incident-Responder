"""The supervisor: routes one incident through triage, diagnosis and fix, stage by stage.

Routing is fixed for now (DESIGN.md section 5; dynamic routing is T16). Every
stage persists to the run store. A run stops at AWAITING_APPROVAL with a
dry-run of the proposed action, or earlier: ESCALATED when a cap stops it or
the fix agent hands it to a human, FAILED when an agent gives no valid answer
or no backend answers. `decide` records a human decision and resumes the run;
only an approved run executes, and only through the guard.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from google.adk.agents.invocation_context import LlmCallsLimitExceededError
from pydantic import BaseModel

from agents.adk import run_agent
from agents.diagnosis import build_diagnosis, diagnosis_message
from agents.fix import build_fix, fix_message
from agents.report import RunReport
from agents.schemas import Approval, ApprovalDecision, Findings, FixClass, FixProposal
from agents.triage import build_triage, triage_message
from config import Settings, load_settings
from demo_env.load import LoadedIncident
from guard.approval import WriteRefused
from llm.client import LlmClient
from llm.errors import CallCapReached, LlmError
from llm.ledger import CallStatus, Ledger
from llm.transport import Transport
from rag.embed import SentenceTransformerEmbedder
from rag.index import RunbookIndex, load_index
from state.states import RunState
from state.store import RunStore
from tools.evidence import EvidenceStore
from tools.read_only import ToolSession
from tools.write import ActionRecord, dry_run, execute

logger = logging.getLogger("supervisor")

TRIAGE_MAX_CALLS = 2
FIX_MAX_CALLS = 3


class Supervisor:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        ledger: Ledger | None = None,
        transport: Transport | None = None,
        runs: RunStore | None = None,
        runbooks: RunbookIndex | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.ledger = ledger
        self.transport = transport
        self.runs = runs or RunStore()
        self.runbooks = _runbooks(self.settings, runbooks)

    def run(self, incident: LoadedIncident) -> RunReport:
        return asyncio.run(self.run_async(incident))

    async def run_async(self, incident: LoadedIncident) -> RunReport:
        incident_id = incident.incident.id
        run_id = f"react-{incident_id}-{uuid.uuid4().hex[:8]}"
        client = LlmClient(
            self.settings,
            run_id=run_id,
            incident_id=incident_id,
            ledger=self.ledger,
            transport=self.transport,
        )
        session = ToolSession(
            run_id=run_id, incident=incident, evidence=EvidenceStore(), runbooks=self.runbooks
        )
        self.runs.create(run_id, incident_id)
        started = time.perf_counter()
        try:
            await asyncio.wait_for(
                self._stages(client, session), timeout=self.settings.limits.run_timeout_seconds
            )
        except TimeoutError:
            self._stop(run_id, RunState.escalated, "run timeout")
        except LlmCallsLimitExceededError:
            self._stop(run_id, RunState.escalated, "agent call cap hit")
        except CallCapReached as error:
            self._stop(run_id, RunState.escalated, str(error))
        except LlmError as error:
            self._stop(run_id, RunState.failed, f"llm: {error}")
        finally:
            self.runs.save_evidence(run_id, session.evidence.items())
            self.runs.set_totals(
                run_id,
                **_totals(client.ledger, run_id),
                duration_ms=(time.perf_counter() - started) * 1000,
            )
            if self.ledger is None:
                client.close()
        report = build_report(self.runs, run_id)
        logger.info(
            "supervisor run=%s incident=%s state=%s reason=%s calls=%d",
            run_id,
            incident_id,
            report.state.value,
            report.stop_reason,
            report.llm_calls,
        )
        return report

    async def _stages(self, client: LlmClient, session: ToolSession) -> None:
        run_id = session.run_id
        alert = session.incident.incident.alert
        services = session.incident.services

        triage_agent, triage_submit = build_triage(client, services)
        await run_agent(
            triage_agent, triage_message(alert, services), max_llm_calls=TRIAGE_MAX_CALLS
        )
        triage = triage_submit.result
        if triage is None:
            return self._no_answer(run_id, "triage", triage_submit.rejections)
        self.runs.advance(run_id, RunState.triaged, payloads={"triage": _json(triage)})

        steps = self.settings.limits.max_react_steps
        diagnosis_agent, findings_submit = build_diagnosis(client, session)
        await run_agent(
            diagnosis_agent,
            diagnosis_message(alert, triage, services, steps),
            max_llm_calls=steps,
        )
        findings = findings_submit.result
        if findings is None:
            return self._no_answer(run_id, "diagnosis", findings_submit.rejections)
        self.runs.advance(run_id, RunState.diagnosed, payloads={"findings": _json(findings)})

        await self._fix(client, session, findings)

    async def _fix(self, client: LlmClient, session: ToolSession, findings: Findings) -> None:
        run_id = session.run_id
        fix_agent, proposal_submit = build_fix(client, session, findings)
        await run_agent(fix_agent, fix_message(findings, session), max_llm_calls=FIX_MAX_CALLS)
        proposal = proposal_submit.result
        if proposal is None:
            return self._no_answer(run_id, "fix", proposal_submit.rejections)
        if proposal.action is FixClass.escalate_human:
            self.runs.advance(run_id, RunState.fix_proposed, payloads={"proposal": _json(proposal)})
            self._stop(run_id, RunState.escalated, "fix agent escalated to a human")
            return
        self.runs.advance(
            run_id,
            RunState.fix_proposed,
            payloads={"proposal": _json(proposal), "dry_run": _json(dry_run(proposal))},
        )
        self.runs.advance(run_id, RunState.awaiting_approval)

    def _no_answer(self, run_id: str, agent: str, rejections: list[str]) -> None:
        if rejections:
            self._stop(run_id, RunState.failed, f"{agent} submissions rejected: {rejections[-1]}")
        else:
            self._stop(run_id, RunState.failed, f"{agent} ended without submitting")

    def _stop(self, run_id: str, state: RunState, reason: str) -> None:
        self.runs.advance(run_id, state, stop_reason=reason)


def _runbooks(settings: Settings, given: RunbookIndex | None) -> RunbookIndex | None:
    """The index every run shares; built or refreshed once per supervisor, never when RAG is off."""
    if not settings.features.rag:
        return None
    if given is not None:
        return given
    return load_index(SentenceTransformerEmbedder(settings.rag.embedding))


def decide(runs: RunStore, approval: Approval) -> RunReport:
    """Record a human decision and resume the run. Repeating the same decision is a no-op."""
    run_id = approval.run_id
    runs.record_approval(approval)
    if runs.get(run_id).state is not RunState.awaiting_approval:
        return build_report(runs, run_id)
    if approval.decision is ApprovalDecision.rejected:
        runs.advance(run_id, RunState.rejected, stop_reason=f"rejected by {approval.decided_by}")
        return build_report(runs, run_id)
    run = runs.advance(run_id, RunState.approved)
    proposal = FixProposal.model_validate(run.payloads["proposal"])
    try:
        record = execute(run, approval, proposal)
    except WriteRefused as refused:
        runs.advance(run_id, RunState.failed, stop_reason=str(refused))
        return build_report(runs, run_id)
    runs.advance(run_id, RunState.executed, payloads={"executed": [_json(record)]})
    runs.advance(run_id, RunState.done)
    return build_report(runs, run_id)


def build_report(runs: RunStore, run_id: str) -> RunReport:
    """The report is read back from the store, so a resumed run reports like a fresh one."""
    run = runs.get(run_id)
    approval = runs.approval(run_id)
    executed = [ActionRecord.model_validate(raw) for raw in run.payloads.get("executed", [])]
    approved = approval is not None and approval.decision is ApprovalDecision.approved
    findings = run.payloads.get("findings")
    proposal = run.payloads.get("proposal")
    return RunReport(
        run_id=run.run_id,
        incident_id=run.incident_id,
        state=run.state,
        escalated=run.state is RunState.escalated,
        stop_reason=run.stop_reason,
        findings=Findings.model_validate(findings) if findings else None,
        proposal=FixProposal.model_validate(proposal) if proposal else None,
        dry_run=run.payloads["dry_run"]["outcome"] if "dry_run" in run.payloads else None,
        approval=approval,
        executed_actions=[f"{record.tool}({record.target})" for record in executed],
        unsafe_actions=0 if approved else len(executed),
        evidence=runs.evidence(run_id),
        llm_calls=run.llm_calls,
        tokens_in=run.tokens_in,
        tokens_out=run.tokens_out,
        cost_usd_equiv=run.cost_usd_equiv,
        duration_ms=run.duration_ms,
    )


def _json(value: BaseModel) -> Any:
    return value.model_dump(mode="json")


def _totals(ledger: Ledger, run_id: str) -> dict[str, float | int]:
    rows = [row for row in ledger.rows(run_id) if row.status in (CallStatus.ok, CallStatus.hit)]
    return {
        "llm_calls": len(rows),
        "tokens_in": sum(row.tokens_in for row in rows),
        "tokens_out": sum(row.tokens_out for row in rows),
        "cost": sum(row.cost_usd_equiv for row in rows),
    }
