"""One task runner for every repo command.

The Makefile delegates here so `make x` and `uv run python tasks.py x` can never
diverge. Windows has no make by default; the python entry point is the real one.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _run(cmd: list[str]) -> int:
    print("+ " + " ".join(cmd))
    return subprocess.call(cmd, cwd=ROOT)


def setup(_: argparse.Namespace) -> int:
    code = _run(["uv", "sync"])
    if code:
        return code
    env = ROOT / ".env"
    if not env.exists():
        shutil.copyfile(ROOT / ".env.example", env)
        print("created .env from .env.example; add a free Gemini key to run live")
    print("setup ok. next: `make lint`, `make test`, or `make smoke` once a key is set.")
    return 0


def up(_: argparse.Namespace) -> int:
    if not shutil.which("docker"):
        print("docker not found. Postgres is only needed for RAG (week 3); week 1 runs without it.")
        return 1
    return _run(["docker", "compose", "up", "-d"])


def down(_: argparse.Namespace) -> int:
    if not shutil.which("docker"):
        print("docker not found; nothing to stop.")
        return 1
    return _run(["docker", "compose", "down"])


def lint(_: argparse.Namespace) -> int:
    return _run(["uv", "run", "ruff", "check", "."]) or _run(
        ["uv", "run", "ruff", "format", "--check", "."]
    )


def fmt(_: argparse.Namespace) -> int:
    return _run(["uv", "run", "ruff", "format", "."]) or _run(
        ["uv", "run", "ruff", "check", "--fix", "."]
    )


def test(args: argparse.Namespace) -> int:
    cmd = ["uv", "run", "pytest"]
    if not args.live:
        cmd += ["-m", "not live"]
    return _run(cmd)


def smoke(args: argparse.Namespace) -> int:
    from llm.smoke import run_smoke

    return run_smoke(backends=args.backends, write=not args.no_write)


def eval_(args: argparse.Namespace) -> int:
    from evals.harness import main as harness_main

    return harness_main(split=args.split, repeats=args.repeats, agent=args.agent)


def run_incident(args: argparse.Namespace) -> int:
    from cli import main as cli_main

    return cli_main(["run", "--incident", args.incident])


def trace(_: argparse.Namespace) -> int:
    print("Tracing lands in T19 (week 4). Nothing to open yet.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tasks.py", description="Incident responder tasks")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("setup").set_defaults(func=setup)
    sub.add_parser("up").set_defaults(func=up)
    sub.add_parser("down").set_defaults(func=down)
    sub.add_parser("lint").set_defaults(func=lint)
    sub.add_parser("fmt").set_defaults(func=fmt)

    p = sub.add_parser("test")
    p.add_argument("--live", action="store_true", help="include tests marked live")
    p.set_defaults(func=test)

    p = sub.add_parser("smoke")
    p.add_argument(
        "--backends", default=None, help="comma-separated subset, default: configured chain"
    )
    p.add_argument("--no-write", action="store_true", help="print the table without writing JSON")
    p.set_defaults(func=smoke)

    p = sub.add_parser("eval")
    p.add_argument("--split", default="dev", choices=["dev", "heldout", "all"])
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--agent", default="stub", help="stub | diagnosis (registered when T08 lands)")
    p.set_defaults(func=eval_)

    p = sub.add_parser("run")
    p.add_argument("--incident", default="S01")
    p.set_defaults(func=run_incident)

    sub.add_parser("trace").set_defaults(func=trace)
    return parser


if __name__ == "__main__":
    parsed = build_parser().parse_args()
    sys.exit(parsed.func(parsed))
