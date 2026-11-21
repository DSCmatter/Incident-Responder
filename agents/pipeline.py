"""Triage then diagnosis for one incident, under the run's call, step and time caps.

This is the T08 slice: no RAG, no verifier, no fix path. A run ends DIAGNOSED
with findings, ESCALATED when a cap stops it, or FAILED when an agent gives no
valid answer or no backend answers.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass

from google.adk.agents.invocation_context import LlmCallsLimitExceededError

from agents.adk import run_agent
from agents.diagnosis import build_diagnosis, diagnosis_message
from agents.report import RunReport
from agents.triage import build_triage, triage_message
from config import Settings, load_settings
from demo_env.load import LoadedIncident
from llm.client import LlmClient
from llm.errors import CallCapReached, LlmError
from llm.ledger import CallStatus, Ledger
from llm.transport import Transport
from state.states import RunState
from tools.evidence import EvidenceStore
from tools.read_only import ToolSession

logger = logging.getLogger("pipeline")

TRIAGE_MAX_CALLS = 2


@dataclass(frozen=True, slots=True)
class Stop:
    state: RunState
    reason: str


class ReactRunner:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        ledger: Ledger | None = None,
        transport: Transport | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.ledger = ledger
        self.transport = transport

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
        session = ToolSession(run_id=run_id, incident=incident, evidence=EvidenceStore())
        started = time.perf_counter()
        report = RunReport(run_id=run_id, incident_id=incident_id, state=RunState.new)
        try:
            report = await asyncio.wait_for(
                self._stages(client, session, report),
                timeout=self.settings.limits.run_timeout_seconds,
            )
        except TimeoutError:
            report = _stopped(report, Stop(RunState.escalated, "run timeout"))
        except LlmCallsLimitExceededError:
            report = _stopped(report, Stop(RunState.escalated, "react step cap hit"))
        except CallCapReached as error:
            report = _stopped(report, Stop(RunState.escalated, str(error)))
        except LlmError as error:
            report = _stopped(report, Stop(RunState.failed, f"llm: {error}"))
        report = report.model_copy(
            update={
                "evidence": session.evidence.items(),
                "duration_ms": (time.perf_counter() - started) * 1000,
                **_totals(client.ledger, run_id),
            }
        )
        logger.info(
            "pipeline run=%s incident=%s state=%s reason=%s calls=%d",
            run_id,
            incident_id,
            report.state.value,
            report.stop_reason,
            report.llm_calls,
        )
        if self.ledger is None:
            client.close()
        return report

    async def _stages(
        self, client: LlmClient, session: ToolSession, report: RunReport
    ) -> RunReport:
        alert = session.incident.incident.alert
        services = session.incident.services

        triage_agent, triage_submit = build_triage(client, services)
        await run_agent(
            triage_agent, triage_message(alert, services), max_llm_calls=TRIAGE_MAX_CALLS
        )
        if triage_submit.result is None:
            return _stopped(report, _no_answer("triage", triage_submit.rejections))
        report = report.model_copy(update={"state": RunState.triaged})

        steps = self.settings.limits.max_react_steps
        diagnosis_agent, findings_submit = build_diagnosis(client, session)
        await run_agent(
            diagnosis_agent,
            diagnosis_message(alert, triage_submit.result, services, steps),
            max_llm_calls=steps,
        )
        if findings_submit.result is None:
            return _stopped(report, _no_answer("diagnosis", findings_submit.rejections))
        return report.model_copy(
            update={"state": RunState.diagnosed, "findings": findings_submit.result}
        )


def _no_answer(agent: str, rejections: list[str]) -> Stop:
    if rejections:
        return Stop(RunState.failed, f"{agent} submissions rejected: {rejections[-1]}")
    return Stop(RunState.failed, f"{agent} ended without submitting")


def _stopped(report: RunReport, stop: Stop) -> RunReport:
    return report.model_copy(
        update={
            "state": stop.state,
            "escalated": stop.state is RunState.escalated,
            "stop_reason": stop.reason,
        }
    )


def _totals(ledger: Ledger, run_id: str) -> dict[str, float | int]:
    rows = [row for row in ledger.rows(run_id) if row.status in (CallStatus.ok, CallStatus.hit)]
    return {
        "llm_calls": len(rows),
        "tokens_in": sum(row.tokens_in for row in rows),
        "tokens_out": sum(row.tokens_out for row in rows),
        "cost_usd_equiv": sum(row.cost_usd_equiv for row in rows),
    }
