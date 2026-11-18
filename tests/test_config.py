from pathlib import Path

import pytest

from config import DEFAULT_CONFIG_PATH, Mode, Settings, load_settings

ROOT = Path(__file__).resolve().parents[1]


def test_repo_config_loads_with_documented_limits() -> None:
    settings = load_settings()
    assert settings.limits.max_llm_calls_per_run == 12
    assert settings.limits.max_react_steps == 6
    assert settings.limits.max_react_steps_fast_path == 3
    assert settings.limits.max_critic_rounds == 2
    assert settings.limits.run_timeout_seconds == 60
    assert settings.llm.mode is Mode.live


def test_chain_naming_an_unknown_backend_is_rejected() -> None:
    data = _raw_config() | {"llm": _raw_config()["llm"] | {"chain": ["gemini", "nope"]}}
    with pytest.raises(ValueError, match="unknown backends"):
        Settings.model_validate(data)


def test_every_chained_backend_needs_a_budget_entry() -> None:
    llm = dict(_raw_config()["llm"])
    llm["daily_budget"] = {"gemini": 200}
    with pytest.raises(ValueError, match="missing entries"):
        Settings.model_validate(_raw_config() | {"llm": llm})


def test_unset_key_removes_backend_from_usable_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    settings = load_settings()
    assert "gemini" not in settings.usable_chain()
    assert "ollama" in settings.usable_chain()


def test_env_override_changes_mode_and_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INCIDENT_LLM_MODE", "replay")
    monkeypatch.setenv("INCIDENT_LLM_CHAIN", "ollama")
    settings = load_settings()
    assert settings.llm.mode is Mode.replay
    assert settings.llm.chain == ["ollama"]


def _raw_config() -> dict:
    import yaml

    return yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
