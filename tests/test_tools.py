"""Tool behaviour against real fixtures: what the model sees, and what is stored."""

from __future__ import annotations

from datetime import timedelta

import pytest

from demo_env.load import INCIDENTS_DIR, load_incident
from tools.evidence import EvidenceStore
from tools.read_only import TOOLS, ToolError, ToolSession, invoke_tool, tool_schemas

S01 = "S01_bad_deploy_env_var"
S02 = "S02_memory_leak"


@pytest.fixture
def s01() -> ToolSession:
    return ToolSession(
        run_id="r1", incident=load_incident(INCIDENTS_DIR / S01), evidence=EvidenceStore()
    )


@pytest.fixture
def s02() -> ToolSession:
    return ToolSession(
        run_id="r2", incident=load_incident(INCIDENTS_DIR / S02), evidence=EvidenceStore()
    )


def test_query_logs_mints_one_evidence_item_with_line_range(s01: ToolSession) -> None:
    out = invoke_tool(
        s01,
        "query_logs",
        '{"service": "checkout-api", "start": "2026-11-12T08:48:00Z", '
        '"end": "2026-11-12T08:52:00Z"}',
    )
    assert out.startswith("[ev_log_1] logs/checkout-api.jsonl:")
    assert "<untrusted_log>" in out
    assert "connection refused" in out
    assert len(s01.evidence) == 1
    stored = s01.evidence.get("ev_log_1")
    assert stored is not None
    assert "config: PAYMENT_BASE_URL resolved to ''" in stored.content


def test_query_logs_pattern_is_a_regex_and_falls_back_to_literal(s01: ToolSession) -> None:
    regex = invoke_tool(
        s01,
        "query_logs",
        '{"service": "checkout-api", "start": "2026-11-12T08:00:00Z", '
        '"end": "2026-11-12T09:30:00Z", "pattern": "5\\\\d\\\\d upstream"}',
    )
    assert "502 upstream" in regex
    literal = invoke_tool(
        s01,
        "query_logs",
        '{"service": "checkout-api", "start": "2026-11-12T08:00:00Z", '
        '"end": "2026-11-12T09:30:00Z", "pattern": "resolved to \'\' ("}',
    )
    assert "PAYMENT_BASE_URL" in literal


def test_query_logs_records_an_empty_window_as_evidence(s01: ToolSession) -> None:
    out = invoke_tool(
        s01,
        "query_logs",
        '{"service": "checkout-api", "start": "2026-11-01T00:00:00Z", '
        '"end": "2026-11-02T00:00:00Z"}',
    )
    assert "no log lines for checkout-api" in out
    assert len(s01.evidence) == 1


def test_query_logs_respects_limit_and_says_so(s01: ToolSession) -> None:
    out = invoke_tool(
        s01,
        "query_logs",
        '{"service": "checkout-api", "start": "2026-11-12T08:00:00Z", '
        '"end": "2026-11-12T09:30:00Z", "limit": 5}',
    )
    assert "older matching lines omitted; showing newest 5" in out
    assert out.count("\n") >= 6


def test_unknown_service_is_refused_with_the_known_list(s01: ToolSession) -> None:
    with pytest.raises(ToolError, match=r"unknown service 'nope'.*checkout-api"):
        invoke_tool(
            s01,
            "query_logs",
            '{"service": "nope", "start": "2026-11-12T08:00:00Z", "end": "2026-11-12T09:00:00Z"}',
        )


def test_invalid_arguments_name_the_tool(s01: ToolSession) -> None:
    with pytest.raises(ToolError, match="invalid arguments for query_logs"):
        invoke_tool(s01, "query_logs", '{"service": "checkout-api"}')


def test_unknown_tool_lists_available_ones(s01: ToolSession) -> None:
    with pytest.raises(ToolError, match="available: query_logs"):
        invoke_tool(s01, "restart_service", "{}")


def test_query_metrics_summarises_a_ramp(s02: ToolSession) -> None:
    out = invoke_tool(
        s02,
        "query_metrics",
        '{"service": "search-api", "metric": "mem_mb", "start": "2026-11-13T12:00:00Z", '
        '"end": "2026-11-13T13:40:00Z"}',
    )
    assert "trend=rising" in out
    assert "max=" in out and "spikes=" in out
    assert s02.evidence.get("ev_metric_1") is not None


def test_query_metrics_for_an_absent_metric_lists_what_exists(s01: ToolSession) -> None:
    out = invoke_tool(
        s01,
        "query_metrics",
        '{"service": "checkout-api", "metric": "db_latency_ms", "start": "2026-11-12T08:00:00Z", '
        '"end": "2026-11-12T09:00:00Z"}',
    )
    assert "available metrics:" in out
    assert "error_rate" in out


def test_recent_deploys_window_is_anchored_to_the_alert(s02: ToolSession) -> None:
    recent = invoke_tool(s02, "list_recent_deploys", '{"hours": 24}')
    assert "no deploys" in recent
    wider = invoke_tool(s02, "list_recent_deploys", '{"hours": 96}')
    assert "dpl-31aa" in wider


def test_deploy_diff_returns_the_patch(s01: ToolSession) -> None:
    out = invoke_tool(s01, "get_deploy_diff", '{"deploy_id": "dpl-4f21"}')
    assert "PAYMENT_BASE_URL" in out
    with pytest.raises(ToolError, match="known deploys: dpl-4f21"):
        invoke_tool(s01, "get_deploy_diff", '{"deploy_id": "dpl-0000"}')


def test_evidence_ids_are_per_kind_and_monotonic(s01: ToolSession) -> None:
    invoke_tool(
        s01,
        "query_logs",
        '{"service": "checkout-api", "start": "2026-11-12T08:00:00Z", "end": "2026-11-12T09:00:00Z"}',
    )
    invoke_tool(s01, "list_recent_deploys", "{}")
    invoke_tool(
        s01,
        "query_logs",
        '{"service": "checkout-api", "start": "2026-11-12T08:00:00Z", "end": "2026-11-12T09:00:00Z"}',
    )
    assert s01.evidence.ids() == ["ev_log_1", "ev_deploy_1", "ev_log_2"]


def test_every_tool_exposes_a_usable_json_schema() -> None:
    schemas = tool_schemas(list(TOOLS))
    assert [schema["name"] for schema in schemas] == list(TOOLS)
    for schema in schemas:
        assert schema["description"]
        assert schema["parameters"]["type"] == "object"
        assert "title" not in schema["parameters"]


def test_alert_anchor_matches_the_fixture(s01: ToolSession) -> None:
    alert = s01.incident.incident.alert.time
    recent = invoke_tool(s01, "list_recent_deploys", "{}")
    assert "dpl-4f21" in recent
    deploy = s01.incident.deploy("dpl-4f21")
    assert deploy is not None
    assert alert - deploy.ts < timedelta(hours=24)
