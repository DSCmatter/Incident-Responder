"""Write tools: dry-run by default, executed only on the demo stack after the guard allows it.

`WRITE_TOOLS` maps every fix class to the one tool that carries it out, with
what its target names and which params it needs. `escalate_human` has no tool:
it hands the incident to a person.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from agents.schemas import Approval, FixClass, FixProposal, Strict
from demo_env.load import LoadedIncident
from guard.approval import authorize
from state.store import RunRecord


class TargetKind(StrEnum):
    service = "service"
    deploy = "deploy"


@dataclass(frozen=True, slots=True)
class WriteTool:
    name: str
    target: TargetKind
    params: tuple[str, ...] = ()


WRITE_TOOLS: dict[FixClass, WriteTool] = {
    FixClass.rollback_deploy: WriteTool("rollback_deploy", TargetKind.deploy),
    FixClass.restart_service: WriteTool("restart_service", TargetKind.service),
    FixClass.config_change: WriteTool("apply_config_change", TargetKind.service, ("key", "value")),
    FixClass.scale_out: WriteTool("scale_service", TargetKind.service, ("replicas",)),
    FixClass.rotate_cert: WriteTool("rotate_certificate", TargetKind.service),
    FixClass.add_index: WriteTool("add_index", TargetKind.service, ("table", "columns")),
    FixClass.free_disk: WriteTool("free_disk", TargetKind.service, ("path",)),
}


class ActionRecord(Strict):
    tool: str
    target: str
    params: dict[str, str]
    dry_run: bool
    outcome: str


def proposal_problems(proposal: FixProposal, incident: LoadedIncident) -> list[str]:
    """Why this proposal could not run on the demo stack; empty when it could."""
    if proposal.action is FixClass.escalate_human:
        return []
    problems = []
    if not proposal.rollback_plan.strip():
        problems.append("rollback_plan is required unless the action is escalate_human")
    tool = WRITE_TOOLS[proposal.action]
    if tool.target is TargetKind.deploy and incident.deploy(proposal.target) is None:
        known = ", ".join(deploy.deploy_id for deploy in incident.deploys) or "none"
        problems.append(f"target {proposal.target!r} is not a deploy id; known: {known}")
    if tool.target is TargetKind.service and proposal.target not in incident.services:
        problems.append(
            f"target {proposal.target!r} is not a service; known: {', '.join(incident.services)}"
        )
    expected = set(tool.params)
    given = set(proposal.params)
    if expected != given:
        problems.append(
            f"{proposal.action.value} takes params {sorted(expected)}, got {sorted(given)}"
        )
    replicas = proposal.params.get("replicas")
    if "replicas" in expected and replicas is not None and not replicas.isdigit():
        problems.append(f"replicas must be a positive integer, got {replicas!r}")
    return problems


def dry_run(proposal: FixProposal) -> ActionRecord:
    tool = WRITE_TOOLS[proposal.action]
    return ActionRecord(
        tool=tool.name,
        target=proposal.target,
        params=dict(proposal.params),
        dry_run=True,
        outcome=f"would call {tool.name}({_args(proposal)})",
    )


def execute(run: RunRecord, approval: Approval | None, proposal: FixProposal) -> ActionRecord:
    """Apply the approved proposal to the demo stack. The guard raises `WriteRefused` first."""
    authorize(run, approval, proposal)
    tool = WRITE_TOOLS[proposal.action]
    return ActionRecord(
        tool=tool.name,
        target=proposal.target,
        params=dict(proposal.params),
        dry_run=False,
        outcome=f"applied {tool.name}({_args(proposal)}) to the demo stack",
    )


def _args(proposal: FixProposal) -> str:
    return ", ".join([proposal.target, *(f"{k}={v}" for k, v in sorted(proposal.params.items()))])
