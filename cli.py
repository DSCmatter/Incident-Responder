"""Command line for one incident.

`run` routes an incident through the supervisor and prints the report. A run
that pauses for approval prints the commands that resume it; `approve` and
`reject` record the decision and print the report again.
"""

from __future__ import annotations

import argparse
import logging
import sys

from agents.report import RunReport, render
from agents.schemas import Approval, ApprovalDecision
from agents.supervisor import Supervisor, decide
from demo_env.load import LoadedIncident, load_split
from state.states import RunState
from state.store import RunStore, UnknownRun

OWN_LOGGERS = ("llm", "supervisor", "guard")
DECISIONS = {"approve": ApprovalDecision.approved, "reject": ApprovalDecision.rejected}


def main(
    argv: list[str] | None = None,
    *,
    supervisor: Supervisor | None = None,
    runs: RunStore | None = None,
) -> int:
    args = _parser().parse_args(argv)
    _configure_logging()
    if args.command == "run":
        incident = _find(args.incident)
        if incident is None:
            known = ", ".join(loaded.incident.id for loaded in load_split("all"))
            print(f"unknown incident {args.incident!r}; known: {known}", file=sys.stderr)
            return 2
        report = (supervisor or Supervisor()).run(incident)
        print(render(report))
        if report.state is RunState.awaiting_approval:
            print(
                "\nNothing has been changed. To decide:\n"
                f"  make approve RUN={report.run_id} BY=<your name>\n"
                f"  make reject RUN={report.run_id} BY=<your name>"
            )
        return _exit_code(report)

    approval = Approval(
        run_id=args.run_id,
        decision=DECISIONS[args.command],
        decided_by=args.by,
        note=args.note,
    )
    try:
        report = decide(runs or RunStore(), approval)
    except UnknownRun:
        print(f"unknown run {args.run_id!r}", file=sys.stderr)
        return 2
    print(render(report))
    return _exit_code(report)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cli.py", description="Run and approve incidents")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run one incident and print the report")
    run.add_argument("--incident", required=True, help="incident id, such as S01")
    for name in DECISIONS:
        decide_parser = sub.add_parser(name, help=f"{name} the fix proposed by a paused run")
        decide_parser.add_argument("--run-id", required=True)
        decide_parser.add_argument("--by", required=True, help="who decided")
        decide_parser.add_argument("--note", default="")
    return parser


def _find(incident_id: str) -> LoadedIncident | None:
    return next((loaded for loaded in load_split("all") if loaded.incident.id == incident_id), None)


def _exit_code(report: RunReport) -> int:
    return 1 if report.state is RunState.failed else 0


def _configure_logging() -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    for name in OWN_LOGGERS:
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            logger.addHandler(handler)


if __name__ == "__main__":
    raise SystemExit(main())
