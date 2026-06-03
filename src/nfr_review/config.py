# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Per-project configuration loader for nfr-review.yaml.

Parses YAML with ruamel.yaml's safe loader and validates structure with
Pydantic. The single public entry point is :func:`load_config`, which always
returns a valid :class:`Config` (defaults when no path is supplied or the file
does not exist) or raises :class:`ConfigError` with a human-readable message.

The CLI (T07) is responsible for translating ``ConfigError`` into a non-zero
exit code; this module never calls ``sys.exit`` directly.
"""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from ruamel.yaml import YAML, YAMLError

from nfr_review.models import Severity


class ConfigError(Exception):
    """Raised when nfr-review.yaml cannot be loaded or fails validation.

    The message is intended to be surfaced verbatim to the user, so it should
    include enough context (path, line/column, field path) to make the failure
    actionable.
    """


class RulesConfig(BaseModel):
    """Rule selection knobs."""

    model_config = ConfigDict(extra="forbid")

    skip: list[str] = Field(default_factory=list)
    include_only: list[str] | None = None


class CollectorsConfig(BaseModel):
    """Collector selection knobs."""

    model_config = ConfigDict(extra="forbid")

    skip: list[str] = Field(default_factory=list)


LlmProvider = Literal["anthropic", "openai", "claude-cli"]


class LlmConfig(BaseModel):
    """LLM backend configuration.

    Env-var overrides: ``NFR_LLM_PROVIDER``, ``NFR_LLM_MODEL``,
    ``NFR_LLM_BASE_URL``, and the var named by *api_key_env_var*.
    """

    model_config = ConfigDict(extra="forbid")

    provider: LlmProvider = "anthropic"
    model: str = "claude-sonnet-4-6-20250514"
    base_url: str | None = None
    api_key_env_var: str = "ANTHROPIC_API_KEY"

    def resolve(self) -> LlmConfig:
        """Return a copy with env-var overrides applied."""
        overrides: dict[str, Any] = {}
        if v := os.environ.get("NFR_LLM_PROVIDER", "").strip():
            overrides["provider"] = v
        if v := os.environ.get("NFR_LLM_MODEL", "").strip():
            overrides["model"] = v
        if v := os.environ.get("NFR_LLM_BASE_URL", "").strip():
            overrides["base_url"] = v
        if not overrides:
            return self
        return self.model_copy(update=overrides)


class Config(BaseModel):
    """Validated nfr-review.yaml configuration.

    All fields have safe defaults so an empty file (or no file at all) yields
    a valid Config.
    """

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    tech: dict[str, bool] = Field(default_factory=dict)
    rules: RulesConfig = Field(default_factory=RulesConfig)
    collectors: CollectorsConfig = Field(default_factory=CollectorsConfig)
    severity_threshold: Severity | None = None
    exclude_paths: list[str] = Field(default_factory=list)
    exclude_test_paths: bool = True
    max_resolve_rounds: int = 2000
    llm: LlmConfig = Field(default_factory=LlmConfig)
    target: Path | None = Field(default=None, exclude=True)


def _format_validation_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "<root>"
        parts.append(f"{loc}: {err['msg']}")
    return "; ".join(parts)


def _parse_yaml(text: str, path: Path) -> Any:
    yaml = YAML(typ="safe")
    try:
        return yaml.load(io.StringIO(text))
    except YAMLError as exc:
        # ruamel exposes problem_mark on parser errors; fall back to str(exc).
        mark = getattr(exc, "problem_mark", None)
        if mark is not None:
            line = mark.line + 1
            col = mark.column + 1
            raise ConfigError(
                f"config file is not valid YAML: {path} (line {line}, column {col}): {exc}"
            ) from exc
        raise ConfigError(f"config file is not valid YAML: {path}: {exc}") from exc


def load_config(path: Path | None) -> Config:
    """Load and validate an nfr-review.yaml config.

    Returns a default :class:`Config` when ``path`` is ``None`` or the file
    does not exist. An empty file is also treated as defaults. Any other
    failure (unreadable file, malformed YAML, schema mismatch) raises
    :class:`ConfigError` with a human-readable message.
    """
    if path is None:
        return Config()

    if not path.exists():
        return Config()

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"config file not readable: {path}: {exc}") from exc

    if text.strip() == "":
        return Config()

    data = _parse_yaml(text, path)

    if data is None:
        return Config()

    if not isinstance(data, dict):
        raise ConfigError(
            f"config file must contain a YAML mapping at the top level: {path} "
            f"(got {type(data).__name__})"
        )

    try:
        return Config(**data)
    except ValidationError as exc:
        raise ConfigError(
            f"config file failed validation: {path}: {_format_validation_error(exc)}"
        ) from exc


__all__ = [
    "Config",
    "ConfigError",
    "CollectorsConfig",
    "LlmConfig",
    "LlmProvider",
    "RulesConfig",
    "load_config",
]
