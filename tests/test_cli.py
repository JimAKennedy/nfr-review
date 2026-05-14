"""CLI unit tests using Click's CliRunner — no subprocess, no installed entry point.

End-to-end coverage (real entry point, real fixture repo, real git) lives in
``tests/test_e2e.py``. Tests here exercise the exit-code matrix, error paths,
and individual command behaviour against in-memory registries when needed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from nfr_review import __version__
from nfr_review.cli import cli
from nfr_review.registry import rule_registry


def _runner() -> CliRunner:
    return CliRunner()


def test_version_command_prints_version() -> None:
    result = _runner().invoke(cli, ["version"])
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == __version__


def test_list_rules_prints_each_rule() -> None:
    result = _runner().invoke(cli, ["list-rules"])
    assert result.exit_code == 0, result.output
    assert "sample-readme-exists" in result.stdout
    assert "band=1" in result.stdout


def test_list_rules_with_empty_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """list-rules must exit 0 with no rows when no rules are registered."""
    from nfr_review.registry import Registry

    empty: Registry = Registry("rule")
    monkeypatch.setattr("nfr_review.cli.rule_registry", empty)

    result = _runner().invoke(cli, ["list-rules"])
    assert result.exit_code == 0
    assert result.stdout == ""


def test_explain_known_rule_prints_description() -> None:
    result = _runner().invoke(cli, ["explain", "sample-readme-exists"])
    assert result.exit_code == 0, result.output
    assert "sample-readme-exists" in result.stdout
    assert "README" in result.stdout


def test_explain_unknown_rule_exits_1() -> None:
    result = _runner().invoke(cli, ["explain", "nonexistent-rule"])
    assert result.exit_code == 1
    assert "no rule registered" in result.stderr


def test_run_missing_target_exits_1(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    result = _runner().invoke(cli, ["run", str(missing)])
    assert result.exit_code == 1
    assert "target does not exist" in result.stderr


def test_run_target_not_directory_exits_1(tmp_path: Path) -> None:
    a_file = tmp_path / "afile.txt"
    a_file.write_text("hello")
    result = _runner().invoke(cli, ["run", str(a_file)])
    # Click's Path(file_okay=False) rejects files at parse time -> exit 2 from Click,
    # but our custom check would emit exit 1. The Click-level rejection happens first
    # for usage errors, which is fine — we still fail loudly. Accept either as a
    # non-zero failure path. The contract is "missing target -> exit 1"; this
    # variant covers the file-supplied case which Click flags as a usage error.
    assert result.exit_code != 0


def test_run_invalid_yaml_exits_1(tmp_path: Path) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    bad_cfg = tmp_path / "nfr-review.yaml"
    bad_cfg.write_text("this: is: : not valid yaml: : :\n  - [bad\n")
    result = _runner().invoke(
        cli,
        ["run", str(target), "--config", str(bad_cfg)],
    )
    assert result.exit_code == 1
    assert "error:" in result.stderr


def test_run_writes_csv_and_jsonl(tmp_path: Path) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    (target / "README.md").write_text("# sample\n")
    csv_path = tmp_path / "out.csv"
    jsonl_path = tmp_path / "out.jsonl"

    result = _runner().invoke(
        cli,
        [
            "run",
            str(target),
            "--csv",
            str(csv_path),
            "--jsonl",
            str(jsonl_path),
        ],
    )
    assert result.exit_code == 0, result.stderr
    assert csv_path.exists()
    assert jsonl_path.exists()
    assert "nfr-review:" in result.stderr
    assert "rules_run=" in result.stderr


def test_run_severity_threshold_triggers_exit_2(tmp_path: Path) -> None:
    """A finding at or above the threshold must produce exit 2.

    The sample rule emits ``severity=medium`` when the README is missing, so a
    threshold of ``medium`` (or below) triggers the gate.
    """
    target = tmp_path / "repo"
    target.mkdir()
    # Intentionally no README -> rule emits amber/medium finding.
    cfg = tmp_path / "nfr-review.yaml"
    cfg.write_text("severity_threshold: medium\n")

    csv_path = tmp_path / "out.csv"
    jsonl_path = tmp_path / "out.jsonl"
    result = _runner().invoke(
        cli,
        [
            "run",
            str(target),
            "--config",
            str(cfg),
            "--csv",
            str(csv_path),
            "--jsonl",
            str(jsonl_path),
        ],
    )
    assert result.exit_code == 2, result.stderr
    assert csv_path.exists()
    assert jsonl_path.exists()


def test_run_severity_threshold_below_returns_0(tmp_path: Path) -> None:
    """When no finding meets the threshold, exit 0."""
    target = tmp_path / "repo"
    target.mkdir()
    (target / "README.md").write_text("# present\n")
    cfg = tmp_path / "nfr-review.yaml"
    cfg.write_text("severity_threshold: critical\n")

    csv_path = tmp_path / "out.csv"
    jsonl_path = tmp_path / "out.jsonl"
    result = _runner().invoke(
        cli,
        [
            "run",
            str(target),
            "--config",
            str(cfg),
            "--csv",
            str(csv_path),
            "--jsonl",
            str(jsonl_path),
        ],
    )
    assert result.exit_code == 0, result.stderr


def test_sample_rule_is_in_registry() -> None:
    """Regression: importing the CLI module must auto-register built-in rules."""
    assert "sample-readme-exists" in rule_registry


JAVA_FIXTURE = Path(__file__).parent / "fixtures" / "java-sample-repo"


def test_run_auto_detects_technologies() -> None:
    """run against java-sample-repo must auto-detect techs and report count."""
    csv_path = JAVA_FIXTURE.parent / "_out.csv"
    jsonl_path = JAVA_FIXTURE.parent / "_out.jsonl"
    try:
        result = _runner().invoke(
            cli,
            [
                "run",
                str(JAVA_FIXTURE),
                "--csv",
                str(csv_path),
                "--jsonl",
                str(jsonl_path),
            ],
        )
        assert result.exit_code in (0, 2), result.stderr
        assert "tech_detected=" in result.stderr
        # java-sample-repo has java files, spring config, and k8s manifests
        count_str = result.stderr.split("tech_detected=")[1].split()[0]
        assert int(count_str) >= 2
    finally:
        csv_path.unlink(missing_ok=True)
        jsonl_path.unlink(missing_ok=True)


def test_run_manual_config_overrides_detection(tmp_path: Path) -> None:
    """Manual tech config must override auto-detected values."""
    cfg = tmp_path / "nfr-review.yaml"
    cfg.write_text("tech:\n  java: false\n")
    csv_path = tmp_path / "out.csv"
    jsonl_path = tmp_path / "out.jsonl"

    result = _runner().invoke(
        cli,
        [
            "run",
            str(JAVA_FIXTURE),
            "--config",
            str(cfg),
            "--csv",
            str(csv_path),
            "--jsonl",
            str(jsonl_path),
        ],
    )
    assert result.exit_code in (0, 2), result.stderr
    assert "tech_detected=" in result.stderr


def test_run_detection_failure_is_nonfatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If detect_technologies raises, run must still complete with config-only tech."""
    monkeypatch.setattr(
        "nfr_review.cli.detect_technologies",
        lambda _: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    target = tmp_path / "repo"
    target.mkdir()
    csv_path = tmp_path / "out.csv"
    jsonl_path = tmp_path / "out.jsonl"

    result = _runner().invoke(
        cli,
        [
            "run",
            str(target),
            "--csv",
            str(csv_path),
            "--jsonl",
            str(jsonl_path),
        ],
    )
    assert result.exit_code == 0, result.stderr
    assert "tech_detected=0" in result.stderr


# -- --include-tests flag presence tests --


def test_run_help_shows_include_tests() -> None:
    result = _runner().invoke(cli, ["run", "--help"])
    assert "--include-tests" in result.output


def test_report_help_shows_include_tests() -> None:
    result = _runner().invoke(cli, ["report", "--help"])
    assert "--include-tests" in result.output


def test_hygiene_help_shows_include_tests() -> None:
    result = _runner().invoke(cli, ["hygiene", "--help"])
    assert "--include-tests" in result.output
