from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.config import (
    CollectorsConfig,
    Config,
    ConfigError,
    LlmConfig,
    RulesConfig,
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
