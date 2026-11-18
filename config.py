"""Typed settings, loaded once per process from config.yaml plus environment.

Owns every limit and budget number the rest of the code enforces. Nothing else
reads config.yaml or os.environ directly, so a limit has exactly one source.
"""

from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, BeforeValidator, Field, model_validator

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config.yaml"
ENV_FILE = REPO_ROOT / ".env"


class Mode(StrEnum):
    """How llm/client.py talks to backends."""

    live = "live"  # call the backend, cache the response
    record = "record"  # same as live, but a cache hit is a bug
    replay = "replay"  # cache only; a miss is an error
    stub = "stub"  # never call out; tests supply scripted responses


class Limits(BaseModel):
    max_llm_calls_per_run: int = Field(gt=0)
    max_react_steps: int = Field(gt=0)
    max_react_steps_fast_path: int = Field(gt=0)
    max_critic_rounds: int = Field(ge=0)
    run_timeout_seconds: float = Field(gt=0)


class Routing(BaseModel):
    runbook_score_threshold: float = Field(ge=0.0, le=1.0)


def _parse_budget(value: object) -> int | None:
    """A budget is a positive call count, or None for no limit (`unlimited`)."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip().lower()
        if text == "unlimited":
            return None
        if text.isdigit():
            value = int(text)
    if isinstance(value, int) and not isinstance(value, bool):
        if value < 0:
            raise ValueError(f"budget must not be negative, got {value}")
        return value
    raise ValueError(f"budget must be an int or 'unlimited', got {value!r}")


Budget = Annotated[int | None, BeforeValidator(_parse_budget)]


class BackendConfig(BaseModel):
    dialect: Literal["gemini", "openai"]
    base_url: str
    model: str
    api_key_env: str | None = None
    timeout_seconds: float = Field(default=60.0, gt=0)
    fallback_models: list[str] = Field(default_factory=list)

    def api_key(self) -> str | None:
        return os.environ.get(self.api_key_env) if self.api_key_env else None

    def is_configured(self) -> bool:
        """A backend with a required key env var is usable only when it is set."""
        return self.api_key_env is None or bool(self.api_key())


class LlmSettings(BaseModel):
    mode: Mode = Mode.live
    chain: list[str] = Field(min_length=1)
    daily_budget: dict[str, Budget]
    backends: dict[str, BackendConfig]

    @model_validator(mode="after")
    def _chain_names_known_backends(self) -> LlmSettings:
        unknown = [name for name in self.chain if name not in self.backends]
        if unknown:
            raise ValueError(f"llm.chain names unknown backends: {unknown}")
        missing_budget = [name for name in self.chain if name not in self.daily_budget]
        if missing_budget:
            raise ValueError(f"llm.daily_budget missing entries for: {missing_budget}")
        return self


class RagSettings(BaseModel):
    k: int = Field(gt=0)
    embedding: str


class Settings(BaseModel):
    limits: Limits
    routing: Routing
    llm: LlmSettings
    rag: RagSettings

    def backend(self, name: str) -> BackendConfig:
        return self.llm.backends[name]

    def usable_chain(self) -> list[str]:
        """Configured chain minus backends whose key env var is unset."""
        return [name for name in self.llm.chain if self.backend(name).is_configured()]


def load_env_file(path: Path = ENV_FILE) -> None:
    """Load KEY=VALUE pairs without overwriting anything already in the environment."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_settings(path: Path | None = None) -> Settings:
    load_env_file()
    config_path = path or DEFAULT_CONFIG_PATH
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    settings = Settings.model_validate(data)

    if mode := os.environ.get("INCIDENT_LLM_MODE"):
        settings.llm.mode = Mode(mode)
    if chain := os.environ.get("INCIDENT_LLM_CHAIN"):
        settings.llm.chain = [part.strip() for part in chain.split(",") if part.strip()]
        settings.llm._chain_names_known_backends()
    return settings
