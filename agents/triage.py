"""Triage: one model call from alert to a `Triage` object."""

from __future__ import annotations

from google.adk.agents import LlmAgent

from agents.adk import ClientModel, SubmitTool
from agents.prompt import load_prompt
from agents.schemas import Triage
from demo_env.models import Alert
from llm.client import LlmClient

PROMPT = load_prompt("triage")


def build_triage(client: LlmClient, services: list[str]) -> tuple[LlmAgent, SubmitTool[Triage]]:
    def check(triage: Triage) -> list[str]:
        if triage.service in services:
            return []
        return [f"service {triage.service!r} is not one of: {', '.join(services)}"]

    submit = SubmitTool(
        "submit_triage", "Submit the triage result. This is the only way to answer.", Triage, check
    )
    agent = LlmAgent(
        name="triage",
        model=ClientModel(
            model="llm-client", client=client, agent="triage", prompt_version=PROMPT.version
        ),
        instruction=lambda _context: PROMPT.text,
        tools=[submit],
    )
    return agent, submit


def triage_message(alert: Alert, services: list[str]) -> str:
    return (
        "<untrusted_alert>\n"
        f"time: {alert.time.isoformat()}\n"
        f"service: {alert.service}\n"
        f"summary: {alert.summary}\n"
        "</untrusted_alert>\n"
        f"Known services: {', '.join(services)}"
    )
