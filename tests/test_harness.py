"""The eval command end to end: every dev incident scored, one JSON file, unsafe fails it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import evals.harness as harness
from agents.report import RunReport
from demo_env.load import LoadedIncident, load_split
from state.states import RunState


class UnsafeRunner:
    def run(self, incident: LoadedIncident) -> RunReport:
        return RunReport(
            run_id="unsafe-1",
            incident_id=incident.incident.id,
            state=RunState.executed,
            unsafe_actions=1,
        )


def test_stub_run_scores_every_dev_incident_and_writes_json(tmp_path: Path) -> None:
    incidents = load_split("dev")

    assert harness.main(split="dev", repeats=1, agent="stub", out_dir=tmp_path) == 0

    files = list(tmp_path.glob("*-dev-stub.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert [row["incident_id"] for row in payload["rows"]] == [
        incident.incident.id for incident in incidents
    ]
    assert payload["aggregate"]["incidents"] == len(incidents)
    assert payload["aggregate"]["repeats"] == 1
    assert payload["meta"]["split"] == "dev"
    assert payload["meta"]["repeats"] == 1
    assert payload["meta"]["agent"] == "stub"
    assert payload["meta"]["generated_at"].endswith("+00:00")


def test_unknown_agent_lists_the_registry(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="stub"):
        harness.main(agent="not-an-agent", out_dir=tmp_path)


def test_one_unsafe_action_fails_the_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(harness.RUNNERS, "unsafe", UnsafeRunner)

    assert harness.main(split="dev", agent="unsafe", out_dir=tmp_path) == 1

    payload = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert payload["aggregate"]["unsafe_total"] >= 1
