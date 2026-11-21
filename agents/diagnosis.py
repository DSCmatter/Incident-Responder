"""Diagnosis: a ReAct loop over the read-only tools that ends in `Findings`."""

from __future__ import annotations

from datetime import timedelta

from google.adk.agents import LlmAgent

from agents.adk import ClientModel, EvidenceTool, SubmitTool
from agents.prompt import load_prompt
from agents.schemas import Findings, Triage
from demo_env.models import Alert
from llm.client import LlmClient
from tools.read_only import ToolSession, available_tools

PROMPT = load_prompt("diagnosis")
TOOL_NAMES = (
    "list_recent_deploys",
    "query_logs",
    "query_metrics",
    "get_deploy_diff",
    "search_runbooks",
)
WINDOW_BEFORE = timedelta(hours=2)
WINDOW_AFTER = timedelta(minutes=15)


def build_diagnosis(
    client: LlmClient, session: ToolSession
) -> tuple[LlmAgent, SubmitTool[Findings]]:
    services = session.incident.services

    def check(findings: Findings) -> list[str]:
        problems = []
        if findings.service not in services:
            problems.append(f"service {findings.service!r} is not one of: {', '.join(services)}")
        for index, claim in enumerate(findings.claims):
            missing = [ev for ev in claim.evidence_ids if not session.evidence.has(ev)]
            if missing:
                problems.append(f"claim {index} cites ids that do not exist: {', '.join(missing)}")
        return problems

    submit = SubmitTool(
        "submit_findings",
        "Submit the diagnosis. This is the only way to answer.",
        Findings,
        check,
    )
    agent = LlmAgent(
        name="diagnosis",
        model=ClientModel(
            model="llm-client", client=client, agent="diagnosis", prompt_version=PROMPT.version
        ),
        instruction=lambda _context: PROMPT.text,
        tools=[
            *(EvidenceTool(name, session) for name in available_tools(session, TOOL_NAMES)),
            submit,
        ],
    )
    return agent, submit


def diagnosis_message(alert: Alert, triage: Triage, services: list[str], max_calls: int) -> str:
    start = (alert.time - WINDOW_BEFORE).isoformat()
    end = (alert.time + WINDOW_AFTER).isoformat()
    return (
        "<untrusted_alert>\n"
        f"time: {alert.time.isoformat()}\n"
        f"service: {alert.service}\n"
        f"summary: {alert.summary}\n"
        "</untrusted_alert>\n"
        f"Triage: {triage.model_dump_json()}\n"
        f"Known services: {', '.join(services)}\n"
        f"Query window: start {start}, end {end}\n"
        f"You have at most {max_calls} model calls, including submit_findings."
    )
