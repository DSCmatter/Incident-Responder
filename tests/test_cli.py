"""`make run` and `make approve` as a person sees them: printed report and exit code."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest

import cli
from agents.supervisor import Supervisor
from llm.ledger import Ledger
from state.store import RunStore
from tests.support import S01_SOLVED, StubTransport, settings_for


@pytest.fixture
def runs(tmp_path: Path) -> Iterator[RunStore]:
    store = RunStore(tmp_path / "runs.db")
    yield store
    store.close()


@pytest.fixture
def ledger(tmp_path: Path) -> Iterator[Ledger]:
    store = Ledger(tmp_path / "ledger.db")
    yield store
    store.close()


def _run_s01(runs: RunStore, ledger: Ledger, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    supervisor = Supervisor(
        settings_for(chain=("openrouter",)),
        ledger=ledger,
        transport=StubTransport(*S01_SOLVED),
        runs=runs,
    )
    code = cli.main(["run", "--incident", "S01"], supervisor=supervisor)
    return code, capsys.readouterr().out


def test_run_prints_the_report_and_how_to_decide(
    runs: RunStore, ledger: Ledger, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = _run_s01(runs, ledger, capsys)

    assert code == 0
    assert "State: awaiting_approval" in out
    assert "Root cause: bad_deploy on checkout-api" in out
    assert "Proposed fix: rollback_deploy dpl-4f21" in out
    assert "dry run: would call rollback_deploy(dpl-4f21)" in out
    assert "ev_deploy_1  deploys.json" in out
    assert re.search(r"make approve RUN=react-S01-\w+ BY=<your name>", out)


def test_approve_resumes_the_printed_run(
    runs: RunStore, ledger: Ledger, capsys: pytest.CaptureFixture[str]
) -> None:
    _, out = _run_s01(runs, ledger, capsys)
    run_id = re.search(r"RUN=(\S+)", out).group(1)

    code = cli.main(["approve", "--run-id", run_id, "--by", "operator"], runs=runs)
    approved = capsys.readouterr().out

    assert code == 0
    assert "State: done" in approved
    assert "Decision: approved by operator" in approved
    assert "Executed: rollback_deploy(dpl-4f21)" in approved


def test_reject_ends_the_run_without_executing(
    runs: RunStore, ledger: Ledger, capsys: pytest.CaptureFixture[str]
) -> None:
    _, out = _run_s01(runs, ledger, capsys)
    run_id = re.search(r"RUN=(\S+)", out).group(1)

    cli.main(["reject", "--run-id", run_id, "--by", "operator", "--note", "not now"], runs=runs)
    rejected = capsys.readouterr().out

    assert "State: rejected (rejected by operator)" in rejected
    assert "Executed:" not in rejected


def test_unknown_incident_and_run_exit_2(
    runs: RunStore, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["run", "--incident", "S99"]) == 2
    assert cli.main(["approve", "--run-id", "nope", "--by", "op"], runs=runs) == 2
    assert "unknown run 'nope'" in capsys.readouterr().err
