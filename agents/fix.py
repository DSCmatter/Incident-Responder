"""Fix: from verified-or-not findings to one `FixProposal` that a human approves."""

from __future__ import annotations

from google.adk.agents import LlmAgent

from agents.adk import ClientModel, EvidenceTool, SubmitTool
from agents.prompt import load_prompt
from agents.schemas import Findings, FixClass, FixProposal
from llm.client import LlmClient
from tools.read_only import ToolSession
from tools.write import WRITE_TOOLS, proposal_problems

PROMPT = load_prompt("fix")


def build_fix(
    client: LlmClient, session: ToolSession, findings: Findings
) -> tuple[LlmAgent, SubmitTool[FixProposal]]:
    def check(proposal: FixProposal) -> list[str]:
        problems = proposal_problems(proposal, session.incident)
        bad = [i for i in proposal.supported_by if not 0 <= i < len(findings.claims)]
        if bad:
            problems.append(
                f"supported_by indexes {bad} are out of range for {len(findings.claims)} claims"
            )
        if not proposal.supported_by and proposal.action is not FixClass.escalate_human:
            problems.append("supported_by must name at least one claim")
        return problems

    submit = SubmitTool(
        "submit_fix_proposal",
        "Submit the fix proposal. This is the only way to answer.",
        FixProposal,
        check,
    )
    agent = LlmAgent(
        name="fix",
        model=ClientModel(
            model="llm-client", client=client, agent="fix", prompt_version=PROMPT.version
        ),
        instruction=lambda _context: PROMPT.text,
        tools=[EvidenceTool("get_deploy_diff", session), submit],
    )
    return agent, submit


def fix_message(findings: Findings, session: ToolSession) -> str:
    incident = session.incident
    actions = "\n".join(
        f"- {action.value}: target is a {tool.target.value}"
        + (f"; params {', '.join(tool.params)}" if tool.params else "; no params")
        for action, tool in WRITE_TOOLS.items()
    )
    deploys = ", ".join(deploy.deploy_id for deploy in incident.deploys) or "none"
    claims = "\n".join(
        f"[{index}] {claim.text} (evidence {', '.join(claim.evidence_ids)}; quote: {claim.quote})"
        for index, claim in enumerate(findings.claims)
    )
    return (
        "<untrusted_findings>\n"
        f"root_cause: {findings.root_cause.value}\n"
        f"service: {findings.service}\n"
        f"summary: {findings.summary}\n"
        f"claims:\n{claims}\n"
        "</untrusted_findings>\n"
        f"Actions:\n{actions}\n- escalate_human: no target needed; use the service name\n"
        f"Known services: {', '.join(incident.services)}\n"
        f"Known deploy ids: {deploys}"
    )
