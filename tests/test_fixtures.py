"""Fixtures must be solvable from their own evidence, consistent, and reproducible."""

from __future__ import annotations

import filecmp
from pathlib import Path

import pytest

from demo_env.faults.render import write_incident
from demo_env.faults.scenarios import SCENARIOS
from demo_env.load import INCIDENTS_DIR, load_split
from demo_env.models import IncidentFiles

DEV_IDS = ["S01", "S02", "S03"]


@pytest.fixture(scope="module")
def dev_incidents():
    return load_split("dev")


def test_three_dev_incidents_load(dev_incidents) -> None:
    assert [loaded.incident.id for loaded in dev_incidents] == DEV_IDS
    for loaded in dev_incidents:
        assert loaded.services, f"{loaded.incident.id} has no services"
        assert loaded.truth.root_cause.value
        assert loaded.truth.acceptable_fixes


def test_truth_patterns_appear_in_their_files(dev_incidents) -> None:
    for loaded in dev_incidents:
        for item in loaded.truth.must_find:
            text = (loaded.files.directory / item.file).read_text(encoding="utf-8")
            assert item.pattern in text, (
                f"{loaded.incident.id}: {item.pattern!r} not in {item.file}"
            )


def test_no_log_line_states_the_cause(dev_incidents) -> None:
    banned = ("root cause", "root_cause", "the problem is", "fix: ")
    for loaded in dev_incidents:
        for service in loaded.services:
            for record in loaded.logs(service):
                lowered = record.entry.msg.lower()
                hits = [phrase for phrase in banned if phrase in lowered]
                assert not hits, f"{loaded.incident.id} {service}:{record.line} leaks {hits}"


def test_metric_windows_are_consistent(dev_incidents) -> None:
    for loaded in dev_incidents:
        for service in loaded.services:
            series = loaded.metrics(service)
            if series is None:
                continue
            for name, points in series.series.items():
                assert points, f"{loaded.incident.id} {service}.{name} is empty"
                stamps = [point.ts for point in points]
                assert stamps == sorted(stamps), f"{loaded.incident.id} {service}.{name} unsorted"
                assert stamps[-1] >= loaded.incident.alert.time, (
                    f"{loaded.incident.id} {service}.{name} ends before the alert"
                )


def test_regeneration_is_byte_identical(tmp_path: Path) -> None:
    name = "S01_bad_deploy_env_var"
    built = SCENARIOS[name]()
    files = IncidentFiles(tmp_path / name)
    write_incident(
        files,
        incident=built.incident,
        truth=built.truth,
        logs=built.writer,
        metrics=built.metrics,
        deploys=built.deploys,
    )
    checked = 0
    for path in sorted((INCIDENTS_DIR / name).rglob("*")):
        if path.is_file():
            assert filecmp.cmp(
                path, tmp_path / name / path.relative_to(INCIDENTS_DIR / name), shallow=False
            ), f"{path.name} differs from a fresh generation"
            checked += 1
    assert checked >= 5
