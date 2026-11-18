"""Generate fixture directories: `python -m demo_env.faults [--only S01]`."""

from __future__ import annotations

import argparse
from pathlib import Path

from demo_env.faults.render import write_incident
from demo_env.faults.scenarios import SCENARIOS
from demo_env.load import INCIDENTS_DIR
from demo_env.models import IncidentFiles


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="demo_env.faults")
    parser.add_argument("--only", default=None, help="scenario directory name or incident id")
    parser.add_argument("--out", type=Path, default=INCIDENTS_DIR)
    args = parser.parse_args(argv)

    selected = {
        name: builder
        for name, builder in SCENARIOS.items()
        if args.only is None or name.startswith(args.only) or name.split("_", 1)[0] == args.only
    }
    if not selected:
        parser.error(f"no scenario matches {args.only!r}")

    for name, builder in selected.items():
        built = builder()
        files = IncidentFiles(args.out / name)
        write_incident(
            files,
            incident=built.incident,
            truth=built.truth,
            logs=built.writer,
            metrics=built.metrics,
            deploys=built.deploys,
        )
        lines = sum(len(entries) for entries in built.writer.lines.values())
        print(
            f"{built.incident.id} {name}: {len(built.writer.lines)} log files, {lines} lines, "
            f"{len(built.metrics)} metric files, {len(built.deploys)} deploys"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
