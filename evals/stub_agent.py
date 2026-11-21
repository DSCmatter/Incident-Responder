"""Pipeline plumbing for the harness: an agent-shaped runner that proves the table fills.

It is never a baseline and never a comparison point, and it never reads truth.yaml,
so a stub score cannot be mistaken for agent quality.
"""

from __future__ import annotations

from agents.report import RunReport
from demo_env.load import LoadedIncident
from state.states import RunState
from tools.evidence import EvidenceItem, EvidenceKind


class StubRunner:
    def run(self, incident: LoadedIncident) -> RunReport:
        alert = incident.incident.alert
        records = incident.logs(alert.service)
        if records:
            first = records[0]
            source = f"logs/{alert.service}.jsonl:{first.line}"
            content = f"{first.entry.ts.isoformat()} {first.entry.level} {first.entry.msg}"
        else:
            source = "incident.yaml:alert"
            content = f"{alert.service}: {alert.summary}"
        evidence = [
            EvidenceItem(
                id="ev_log_1",
                kind=EvidenceKind.log,
                source=source,
                content=content,
                query="stub",
            )
        ]
        return RunReport(
            run_id=f"stub-{incident.incident.id}",
            incident_id=incident.incident.id,
            state=RunState.escalated,
            escalated=True,
            stop_reason="stub agent",
            evidence=evidence,
        )
