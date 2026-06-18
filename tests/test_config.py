from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from nfr_review.config import (
    CATEGORY_ALIASES,
    DEFAULT_CATEGORY_WEIGHTS,
    DEFAULT_DESIGN_CHANGE_THRESHOLDS,
    DEFAULT_SEVERITY_DEDUCTIONS,
    ISO_25010_CATEGORIES,
    CollectorsConfig,
    Config,
    ConfigError,
    DesignChangeConfig,
    LlmConfig,
    NfrTargetsConfig,
    RulesConfig,
    ScoringConfig,
    load_config,
)

FIXTURES = Path(__file__).parent / "fixtures" / "configs"


def test_load_config_none_returns_defaults() -> None:
    cfg = load_config(None)
    assert isinstance(cfg, Config)
    assert cfg.version == 1
    assert cfg.tech == {}
    assert cfg.rules == RulesConfig()
    assert cfg.collectors == CollectorsConfig()
    assert cfg.severity_threshold is None


def test_load_config_missing_path_returns_defaults(tmp_path: Path) -> None:
    cfg = load_config(tmp_path / "does-not-exist.yaml")
    assert cfg == Config()


def test_load_config_empty_file_returns_defaults(tmp_path: Path) -> None:
    p = tmp_path / "nfr-review.yaml"
    p.write_text("", encoding="utf-8")
    cfg = load_config(p)
    assert cfg == Config()


def test_load_config_whitespace_only_file_returns_defaults(tmp_path: Path) -> None:
    p = tmp_path / "nfr-review.yaml"
    p.write_text("   \n\n  \n", encoding="utf-8")
    cfg = load_config(p)
    assert cfg == Config()


def test_load_config_comments_only_file_returns_defaults(tmp_path: Path) -> None:
    p = tmp_path / "nfr-review.yaml"
    p.write_text("# only a comment\n", encoding="utf-8")
    cfg = load_config(p)
    assert cfg == Config()


def test_load_config_valid_fixture() -> None:
    cfg = load_config(FIXTURES / "valid.yaml")
    assert cfg.version == 1
    assert cfg.tech == {"kafka": False, "apim": True, "spring_boot": True}
    assert cfg.rules.skip == ["rule-needs-llm", "rule-needs-kafka"]
    assert cfg.rules.include_only == ["sample-readme-exists", "sample-pom-exists"]
    assert cfg.collectors.skip == ["llm_summarizer"]
    assert cfg.severity_threshold == "high"


def test_load_config_malformed_yaml_raises_with_position() -> None:
    with pytest.raises(ConfigError) as excinfo:
        load_config(FIXTURES / "invalid.yaml")
    msg = str(excinfo.value)
    assert "not valid YAML" in msg
    assert "invalid.yaml" in msg
    # ruamel reports a problem mark for parser errors -> we surface line/column.
    assert "line" in msg and "column" in msg


def test_load_config_unknown_top_level_key_rejected() -> None:
    with pytest.raises(ConfigError) as excinfo:
        load_config(FIXTURES / "missing-required-key.yaml")
    msg = str(excinfo.value)
    assert "failed validation" in msg
    assert "unknown_top_level_key" in msg


def test_invalid_severity_threshold_rejected(tmp_path: Path) -> None:
    p = tmp_path / "nfr-review.yaml"
    p.write_text("severity_threshold: fatal\n", encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        load_config(p)
    assert "severity_threshold" in str(excinfo.value)


def test_non_list_rules_skip_rejected(tmp_path: Path) -> None:
    p = tmp_path / "nfr-review.yaml"
    p.write_text("rules:\n  skip: not-a-list\n", encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        load_config(p)
    msg = str(excinfo.value)
    assert "rules" in msg and "skip" in msg


def test_unknown_nested_key_rejected(tmp_path: Path) -> None:
    p = tmp_path / "nfr-review.yaml"
    p.write_text("rules:\n  bogus: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        load_config(p)
    assert "bogus" in str(excinfo.value)


def test_top_level_must_be_mapping(tmp_path: Path) -> None:
    p = tmp_path / "nfr-review.yaml"
    p.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        load_config(p)
    assert "mapping" in str(excinfo.value)


def test_unreadable_file_raises_config_error(tmp_path: Path) -> None:
    # A directory at the path makes read_text raise OSError without
    # tripping Path.exists() into False.
    p = tmp_path / "nfr-review.yaml"
    p.mkdir()
    with pytest.raises(ConfigError) as excinfo:
        load_config(p)
    assert "not readable" in str(excinfo.value) or "failed" in str(excinfo.value)


def test_default_config_is_valid() -> None:
    cfg = Config()
    # round-trips cleanly through model_dump/model_validate.
    assert Config.model_validate(cfg.model_dump()) == cfg


def test_extra_forbid_on_root() -> None:
    with pytest.raises(ConfigError):
        # Round-trips via load_config to confirm the wrapping behavior.
        from tempfile import NamedTemporaryFile

        with NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write("totally_unknown: 1\n")
            tmp = Path(f.name)
        try:
            load_config(tmp)
        finally:
            tmp.unlink(missing_ok=True)


def test_include_only_can_be_explicit_null(tmp_path: Path) -> None:
    p = tmp_path / "nfr-review.yaml"
    p.write_text("rules:\n  include_only: null\n", encoding="utf-8")
    cfg = load_config(p)
    assert cfg.rules.include_only is None


def test_config_default_exclude_test_paths_true() -> None:
    cfg = Config()
    assert cfg.exclude_test_paths is True


def test_config_default_exclude_paths_empty() -> None:
    cfg = Config()
    assert cfg.exclude_paths == []


def test_config_exclude_paths_from_yaml(tmp_path: Path) -> None:
    p = tmp_path / "nfr-review.yaml"
    p.write_text("exclude_paths:\n  - 'vendor/'\n  - 'generated/'\n", encoding="utf-8")
    cfg = load_config(p)
    assert cfg.exclude_paths == ["vendor/", "generated/"]


def test_config_exclude_test_paths_false_from_yaml(tmp_path: Path) -> None:
    p = tmp_path / "nfr-review.yaml"
    p.write_text("exclude_test_paths: false\n", encoding="utf-8")
    cfg = load_config(p)
    assert cfg.exclude_test_paths is False


def test_config_model_copy_exclude_test_paths() -> None:
    cfg = Config()
    assert cfg.exclude_test_paths is True
    updated = cfg.model_copy(update={"exclude_test_paths": False})
    assert updated.exclude_test_paths is False
    assert cfg.exclude_test_paths is True


# ---------------------------------------------------------------------------
# LlmConfig in nfr-review.yaml
# ---------------------------------------------------------------------------


def test_config_default_llm_config() -> None:
    cfg = Config()
    assert isinstance(cfg.llm, LlmConfig)
    assert cfg.llm.provider == "anthropic"


def test_config_llm_from_yaml(tmp_path: Path) -> None:
    p = tmp_path / "nfr-review.yaml"
    p.write_text(
        "llm:\n  provider: openai\n  model: gpt-4o\n"
        "  base_url: http://localhost:11434/v1\n"
        "  api_key_env_var: OPENAI_API_KEY\n",
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.llm.provider == "openai"
    assert cfg.llm.model == "gpt-4o"
    assert cfg.llm.base_url == "http://localhost:11434/v1"
    assert cfg.llm.api_key_env_var == "OPENAI_API_KEY"


def test_config_llm_claude_cli_from_yaml(tmp_path: Path) -> None:
    p = tmp_path / "nfr-review.yaml"
    p.write_text("llm:\n  provider: claude-cli\n", encoding="utf-8")
    cfg = load_config(p)
    assert cfg.llm.provider == "claude-cli"


def test_config_llm_invalid_provider_rejected(tmp_path: Path) -> None:
    p = tmp_path / "nfr-review.yaml"
    p.write_text("llm:\n  provider: bogus\n", encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        load_config(p)
    assert "provider" in str(excinfo.value)


def test_config_llm_unknown_key_rejected(tmp_path: Path) -> None:
    p = tmp_path / "nfr-review.yaml"
    p.write_text("llm:\n  unknown_field: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        load_config(p)
    assert "unknown_field" in str(excinfo.value)


# ---------------------------------------------------------------------------
# ScoringConfig
# ---------------------------------------------------------------------------


def test_config_default_scoring_config() -> None:
    cfg = Config()
    assert isinstance(cfg.scoring, ScoringConfig)
    assert cfg.scoring.category_weights == DEFAULT_CATEGORY_WEIGHTS
    assert cfg.scoring.severity_deductions == DEFAULT_SEVERITY_DEDUCTIONS
    assert cfg.scoring.category_aliases == CATEGORY_ALIASES


def test_scoring_config_iso_categories_match_default_weights() -> None:
    for cat in ISO_25010_CATEGORIES:
        assert cat in DEFAULT_CATEGORY_WEIGHTS


def test_scoring_config_from_yaml(tmp_path: Path) -> None:
    p = tmp_path / "nfr-review.yaml"
    p.write_text(
        "scoring:\n"
        "  category_weights:\n"
        "    security: 2.0\n"
        "    reliability: 1.5\n"
        "    performance: 1.0\n"
        "    maintainability: 0.5\n",
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.scoring.category_weights["security"] == 2.0
    assert cfg.scoring.category_weights["reliability"] == 1.5
    assert cfg.scoring.category_weights["maintainability"] == 0.5


def test_scoring_config_custom_severity_deductions(tmp_path: Path) -> None:
    p = tmp_path / "nfr-review.yaml"
    p.write_text(
        "scoring:\n"
        "  severity_deductions:\n"
        "    critical: 20\n"
        "    high: 10\n"
        "    medium: 5\n"
        "    low: 2\n"
        "    info: 0\n",
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.scoring.severity_deductions["critical"] == 20
    assert cfg.scoring.severity_deductions["high"] == 10


def test_scoring_config_custom_aliases(tmp_path: Path) -> None:
    p = tmp_path / "nfr-review.yaml"
    p.write_text(
        "scoring:\n"
        "  category_aliases:\n"
        "    observability: reliability\n"
        "    ops: maintainability\n"
        "    infra: maintainability\n",
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.scoring.category_aliases["infra"] == "maintainability"


def test_scoring_config_unknown_key_rejected(tmp_path: Path) -> None:
    p = tmp_path / "nfr-review.yaml"
    p.write_text("scoring:\n  bogus_field: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        load_config(p)
    assert "bogus_field" in str(excinfo.value)


def test_scoring_config_round_trip() -> None:
    cfg = ScoringConfig()
    assert ScoringConfig.model_validate(cfg.model_dump()) == cfg


def test_scoring_config_independent_defaults() -> None:
    a = ScoringConfig()
    b = ScoringConfig()
    a.category_weights["security"] = 99.0
    assert b.category_weights["security"] == 1.0


# ---------------------------------------------------------------------------
# ScoringConfig.merge — repo-local overrides on central defaults
# ---------------------------------------------------------------------------


def test_scoring_merge_overrides_specific_weight() -> None:
    central = ScoringConfig()
    repo = ScoringConfig(category_weights={"security": 2.0})
    merged = central.merge(repo)
    assert merged.category_weights["security"] == 2.0
    assert merged.category_weights["reliability"] == 1.0
    assert merged.category_weights["performance"] == 1.0
    assert merged.category_weights["maintainability"] == 1.0


def test_scoring_merge_preserves_central_only_keys() -> None:
    central = ScoringConfig(category_aliases={"observability": "reliability", "infra": "ops"})
    repo = ScoringConfig(category_aliases={"infra": "maintainability"})
    merged = central.merge(repo)
    assert merged.category_aliases["observability"] == "reliability"
    assert merged.category_aliases["infra"] == "maintainability"


def test_scoring_merge_overrides_severity_deductions() -> None:
    central = ScoringConfig()
    repo = ScoringConfig(severity_deductions={"critical": 20, "high": 10})
    merged = central.merge(repo)
    assert merged.severity_deductions["critical"] == 20
    assert merged.severity_deductions["high"] == 10
    assert merged.severity_deductions["medium"] == DEFAULT_SEVERITY_DEDUCTIONS["medium"]


def test_scoring_merge_does_not_mutate_originals() -> None:
    central = ScoringConfig()
    repo = ScoringConfig(category_weights={"security": 5.0})
    merged = central.merge(repo)
    assert central.category_weights["security"] == 1.0
    assert merged.category_weights["security"] == 5.0


def test_scoring_merge_both_defaults_is_identity() -> None:
    a = ScoringConfig()
    b = ScoringConfig()
    merged = a.merge(b)
    assert merged == a


def test_scoring_merge_adds_new_alias() -> None:
    central = ScoringConfig()
    repo = ScoringConfig(category_aliases={"devops": "maintainability"})
    merged = central.merge(repo)
    assert merged.category_aliases["devops"] == "maintainability"
    assert "observability" in merged.category_aliases


# ---------------------------------------------------------------------------
# Config.with_repo_scoring — full config merge
# ---------------------------------------------------------------------------


def test_config_with_repo_scoring_merges_weights(tmp_path: Path) -> None:
    central_path = tmp_path / "central.yaml"
    central_path.write_text(
        "scoring:\n"
        "  category_weights:\n"
        "    security: 1.0\n"
        "    reliability: 1.0\n"
        "    performance: 1.0\n"
        "    maintainability: 1.0\n",
        encoding="utf-8",
    )
    repo_path = tmp_path / "repo.yaml"
    repo_path.write_text(
        "scoring:\n  category_weights:\n    security: 3.0\n",
        encoding="utf-8",
    )
    central = load_config(central_path)
    repo = load_config(repo_path)
    merged = central.with_repo_scoring(repo)
    assert merged.scoring.category_weights["security"] == 3.0
    assert merged.scoring.category_weights["reliability"] == 1.0
    assert merged.rules == central.rules


def test_config_with_repo_scoring_preserves_non_scoring_fields() -> None:
    central = Config(
        tech={"kafka": True},
        rules=RulesConfig(skip=["some-rule"]),
        scoring=ScoringConfig(category_weights={"security": 1.0}),
    )
    repo = Config(scoring=ScoringConfig(category_weights={"security": 2.0}))
    merged = central.with_repo_scoring(repo)
    assert merged.tech == {"kafka": True}
    assert merged.rules.skip == ["some-rule"]
    assert merged.scoring.category_weights["security"] == 2.0


# ---------------------------------------------------------------------------
# nfr_targets config block
# ---------------------------------------------------------------------------


class TestNfrTargetsConfig:
    def test_defaults_empty(self) -> None:
        cfg = Config()
        assert cfg.nfr_targets.latency_p95_ms == {}
        assert cfg.nfr_targets.throughput_rps_min is None
        assert cfg.nfr_targets.custom_thresholds == {}

    def test_explicit_targets(self) -> None:
        cfg = Config(
            nfr_targets=NfrTargetsConfig(
                latency_p95_ms={"/api/orders": 200, "/api/health": 50},
                throughput_rps_min=100,
            ),
        )
        assert cfg.nfr_targets.latency_p95_ms["/api/orders"] == 200
        assert cfg.nfr_targets.throughput_rps_min == 100

    def test_custom_thresholds(self) -> None:
        cfg = Config(
            nfr_targets=NfrTargetsConfig(
                custom_thresholds={"error_rate_pct": 0.1},
            ),
        )
        assert cfg.nfr_targets.custom_thresholds["error_rate_pct"] == 0.1

    def test_nfr_targets_from_yaml(self, tmp_path: Path) -> None:
        p = tmp_path / "nfr-review.yaml"
        p.write_text(
            "version: 1\n"
            "nfr_targets:\n"
            "  latency_p95_ms:\n"
            "    /api/orders: 200\n"
            "    /api/health: 50\n"
            "  throughput_rps_min: 100\n",
            encoding="utf-8",
        )
        cfg = load_config(p)
        assert cfg.nfr_targets.latency_p95_ms["/api/orders"] == 200
        assert cfg.nfr_targets.throughput_rps_min == 100

    def test_nfr_targets_absent_in_yaml(self, tmp_path: Path) -> None:
        p = tmp_path / "nfr-review.yaml"
        p.write_text("version: 1\n", encoding="utf-8")
        cfg = load_config(p)
        assert cfg.nfr_targets.latency_p95_ms == {}

    def test_nfr_targets_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            NfrTargetsConfig(bogus="bad")


class TestDesignChangeConfig:
    def test_default_thresholds(self) -> None:
        cfg = Config()
        assert isinstance(cfg.design_change, DesignChangeConfig)
        assert cfg.design_change.thresholds == DEFAULT_DESIGN_CHANGE_THRESHOLDS
        assert cfg.design_change.thresholds["class_count"] == 20.0

    def test_yaml_override(self, tmp_path: Path) -> None:
        p = tmp_path / "nfr-review.yaml"
        p.write_text(
            "version: 1\ndesign_change:\n  thresholds:\n    class_count: 50.0\n",
            encoding="utf-8",
        )
        cfg = load_config(p)
        assert cfg.design_change.thresholds["class_count"] == 50.0

    def test_yaml_override_replaces_all(self, tmp_path: Path) -> None:
        p = tmp_path / "nfr-review.yaml"
        p.write_text(
            "version: 1\ndesign_change:\n  thresholds:\n    class_count: 50.0\n",
            encoding="utf-8",
        )
        cfg = load_config(p)
        assert len(cfg.design_change.thresholds) == 1
        assert "test_coverage" not in cfg.design_change.thresholds

    def test_absent_in_yaml_uses_defaults(self, tmp_path: Path) -> None:
        p = tmp_path / "nfr-review.yaml"
        p.write_text("version: 1\n", encoding="utf-8")
        cfg = load_config(p)
        assert cfg.design_change.thresholds == DEFAULT_DESIGN_CHANGE_THRESHOLDS

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            DesignChangeConfig(bogus="bad")

    def test_force_standard_config_resets_to_defaults(self) -> None:
        custom = DesignChangeConfig(thresholds={"class_count": 99.0})
        assert custom.thresholds != DEFAULT_DESIGN_CHANGE_THRESHOLDS
        standard = DesignChangeConfig()
        assert standard.thresholds == DEFAULT_DESIGN_CHANGE_THRESHOLDS
