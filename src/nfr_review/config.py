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

from nfr_review.models import Origin, Severity


# nfr-review:skip(python-dormant-classes) reason: caught by cli.py run/report commands
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
    model: str = "claude-sonnet-4-6"
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
        resolved = self.model_copy(update=overrides)
        if "provider" in overrides and "api_key_env_var" not in overrides:
            _provider_key_map = {
                "anthropic": "ANTHROPIC_API_KEY",
                "openai": "OPENAI_API_KEY",
            }
            if new_key := _provider_key_map.get(resolved.provider):
                if new_key != resolved.api_key_env_var:
                    resolved = resolved.model_copy(update={"api_key_env_var": new_key})
        return resolved


ISO_25010_CATEGORIES: tuple[str, ...] = (
    "security",
    "reliability",
    "performance",
    "maintainability",
)

DEFAULT_CATEGORY_WEIGHTS: dict[str, float] = {
    "security": 1.0,
    "reliability": 1.0,
    "performance": 1.0,
    "maintainability": 1.0,
    "OTEL": 1.0,
    "structure": 1.0,
}

DEFAULT_SEVERITY_DEDUCTIONS: dict[str, int] = {
    "critical": 15,
    "high": 8,
    "medium": 3,
    "low": 1,
    "info": 0,
}

CATEGORY_ALIASES: dict[str, str] = {
    "observability": "reliability",
    "obs": "reliability",
    "ops": "maintainability",
}


class ScoringConfig(BaseModel):
    """Scoring weights and severity deductions aligned with ISO/IEC 25010.

    Supports two-level configuration: a central config provides defaults,
    and each repo can override specific weights via its own nfr-review.yaml.
    Use :meth:`merge` to apply repo-local overrides onto central defaults.
    """

    model_config = ConfigDict(extra="forbid")

    category_weights: dict[str, float] = Field(
        default_factory=lambda: dict(DEFAULT_CATEGORY_WEIGHTS),
    )
    severity_deductions: dict[str, int] = Field(
        default_factory=lambda: dict(DEFAULT_SEVERITY_DEDUCTIONS),
    )
    category_aliases: dict[str, str] = Field(
        default_factory=lambda: dict(CATEGORY_ALIASES),
    )

    def merge(self, overrides: ScoringConfig) -> ScoringConfig:
        """Return a new ScoringConfig with *overrides* applied on top of self.

        Dict fields are shallow-merged: keys present in *overrides* win,
        keys only in *self* are preserved.  This lets a repo-local config
        override ``security: 2.0`` without having to repeat every other weight.
        """
        return ScoringConfig(
            category_weights={**self.category_weights, **overrides.category_weights},
            severity_deductions={**self.severity_deductions, **overrides.severity_deductions},
            category_aliases={**self.category_aliases, **overrides.category_aliases},
        )


class NfrTargetsConfig(BaseModel):
    """Declarative performance targets for Band 3 quantitative rules."""

    model_config = ConfigDict(extra="forbid")

    latency_p95_ms: dict[str, int] = Field(default_factory=dict)
    throughput_rps_min: int | None = None
    custom_thresholds: dict[str, Any] = Field(default_factory=dict)


DEFAULT_DEPENDENCY_PATHS: list[str] = [
    "vendor/*",
    "vendored/*",
    "third_party/*",
    "third-party/*",
    "thirdparty/*",
    "*.min.js",
    "*.min.css",
]

DEFAULT_DESIGN_CHANGE_THRESHOLDS: dict[str, float] = {
    "class_count": 20.0,
    "jdepend_instability": 15.0,
    "dormant_class_count": 25.0,
    "dependency_count": 30.0,
    "test_coverage": 5.0,
    "adr_count": 1.0,
    "api_endpoint_count": 1.0,
    "bounded_context_count": 1.0,
    "integration_point_count": 1.0,
    "deployment_service_count": 1.0,
    "schema_migration_count": 1.0,
}


class DesignChangeConfig(BaseModel):
    """Configuration for design-change detection thresholds."""

    model_config = ConfigDict(extra="forbid")

    thresholds: dict[str, float] = Field(
        default_factory=lambda: dict(DEFAULT_DESIGN_CHANGE_THRESHOLDS),
    )


class GraphifyConfig(BaseModel):
    """Configuration for Graphify structural analysis integration."""

    model_config = ConfigDict(extra="forbid")

    query_enabled: bool = True
    mcp_enabled: bool = False
    graph_path: str | None = None


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
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    design_change: DesignChangeConfig = Field(default_factory=DesignChangeConfig)
    graphify: GraphifyConfig = Field(default_factory=GraphifyConfig)
    nfr_targets: NfrTargetsConfig = Field(default_factory=NfrTargetsConfig)
    dependency_paths: list[str] = Field(
        default_factory=lambda: list(DEFAULT_DEPENDENCY_PATHS),
    )
    origin_filter: Origin | None = None
    otel_traces: Path | None = None
    target: Path | None = Field(default=None, exclude=True)

    def with_repo_scoring(self, repo_config: Config) -> Config:
        """Return a copy with scoring merged from *repo_config*.

        Central config provides defaults; repo-local config overrides
        specific weights/deductions/aliases.  Non-scoring fields from
        the repo config are ignored — only ``scoring`` is merged.
        """
        merged_scoring = self.scoring.merge(repo_config.scoring)
        return self.model_copy(update={"scoring": merged_scoring})


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
    "CATEGORY_ALIASES",
    "Config",
    "ConfigError",
    "CollectorsConfig",
    "DEFAULT_CATEGORY_WEIGHTS",
    "DEFAULT_DEPENDENCY_PATHS",
    "DEFAULT_DESIGN_CHANGE_THRESHOLDS",
    "DEFAULT_SEVERITY_DEDUCTIONS",
    "DesignChangeConfig",
    "ISO_25010_CATEGORIES",
    "LlmConfig",
    "LlmProvider",
    "NfrTargetsConfig",
    "RulesConfig",
    "ScoringConfig",
    "load_config",
]
