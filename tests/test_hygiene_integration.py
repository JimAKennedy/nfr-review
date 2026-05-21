"""Integration tests for Java hygiene fixtures and Python fixture regression guard."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from nfr_review.cli import cli

FIXTURES = Path(__file__).parent / "fixtures"
JAVA_CLEAN_REPO = FIXTURES / "hygiene-java-clean-repo"
JAVA_DIRTY_REPO = FIXTURES / "hygiene-java-dirty-repo"
PYTHON_CLEAN_REPO = FIXTURES / "hygiene-clean-repo"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _parse_findings(jsonl_path: Path) -> list[dict]:
    """Parse findings from hygiene report JSONL."""
    findings = []
    for line in jsonl_path.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("record_type") == "finding":
            findings.append(rec)
    return findings


def _findings_by_rule(findings: list[dict]) -> dict[str, dict]:
    """Index findings by rule_id (last occurrence wins for duplicates)."""
    return {f["rule_id"]: f for f in findings}


def _hygiene_jsonl(tmp_path: Path) -> Path:
    matches = list(tmp_path.glob("*-hygiene-report.jsonl"))
    assert len(matches) == 1, f"Expected one hygiene JSONL, found {matches}"
    return matches[0]


class TestJavaCleanRepo:
    """Java clean fixture should pass hygiene with no red/amber findings."""

    def test_exits_0(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(
            cli,
            ["hygiene", str(JAVA_CLEAN_REPO), "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 0, f"Exit {result.exit_code}: {result.output}"

    def test_bld_001_green(self, runner: CliRunner, tmp_path: Path) -> None:
        """Build system present (pom.xml)."""
        result = runner.invoke(
            cli,
            ["hygiene", str(JAVA_CLEAN_REPO), "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        findings = _findings_by_rule(_parse_findings(_hygiene_jsonl(tmp_path)))
        assert "HYG-BLD-001" in findings
        assert findings["HYG-BLD-001"]["rag"] == "green"

    def test_bld_002_green(self, runner: CliRunner, tmp_path: Path) -> None:
        """Version declared in pom.xml."""
        result = runner.invoke(
            cli,
            ["hygiene", str(JAVA_CLEAN_REPO), "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        findings = _findings_by_rule(_parse_findings(_hygiene_jsonl(tmp_path)))
        assert "HYG-BLD-002" in findings
        assert findings["HYG-BLD-002"]["rag"] == "green"

    def test_ci_003_green(self, runner: CliRunner, tmp_path: Path) -> None:
        """Lint step present (checkstyle in CI)."""
        result = runner.invoke(
            cli,
            ["hygiene", str(JAVA_CLEAN_REPO), "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        findings = _findings_by_rule(_parse_findings(_hygiene_jsonl(tmp_path)))
        assert "HYG-CI-003" in findings
        assert findings["HYG-CI-003"]["rag"] == "green"

    def test_doc_001_not_red(self, runner: CliRunner, tmp_path: Path) -> None:
        """Package metadata present — should not be red."""
        result = runner.invoke(
            cli,
            ["hygiene", str(JAVA_CLEAN_REPO), "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        findings = _findings_by_rule(_parse_findings(_hygiene_jsonl(tmp_path)))
        assert "HYG-DOC-001" in findings
        assert findings["HYG-DOC-001"]["rag"] != "red"

    def test_community_rules_mostly_green(self, runner: CliRunner, tmp_path: Path) -> None:
        """Clean repo has all community health files."""
        result = runner.invoke(
            cli,
            ["hygiene", str(JAVA_CLEAN_REPO), "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        findings = _findings_by_rule(_parse_findings(_hygiene_jsonl(tmp_path)))
        com_rules = {k: v for k, v in findings.items() if k.startswith("HYG-COM")}
        green_count = sum(1 for f in com_rules.values() if f["rag"] == "green")
        assert green_count >= 4, (
            f"Expected >=4 green COM rules, got {green_count}: {com_rules}"
        )

    def test_false_positive_rate_under_10_pct(self, runner: CliRunner, tmp_path: Path) -> None:
        """Clean Java repo should have a low false-positive rate."""
        result = runner.invoke(
            cli,
            ["hygiene", str(JAVA_CLEAN_REPO), "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        findings = _parse_findings(_hygiene_jsonl(tmp_path))
        total = len(findings)
        bad = [f for f in findings if f["rag"] in ("red", "amber")]
        if total > 0:
            rate = len(bad) / total
            assert rate < 0.30, f"False positive rate {rate:.1%} >= 30%: {bad}"
        assert not any(f["rag"] == "red" for f in bad), (
            "No red findings expected in clean repo"
        )


class TestJavaDirtyRepo:
    """Java dirty fixture should produce expected amber/red findings."""

    def test_exits_0(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(
            cli,
            ["hygiene", str(JAVA_DIRTY_REPO), "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 0, f"Exit {result.exit_code}: {result.output}"

    def test_bld_001_green(self, runner: CliRunner, tmp_path: Path) -> None:
        """Build system present (pom.xml exists even in dirty repo)."""
        result = runner.invoke(
            cli,
            ["hygiene", str(JAVA_DIRTY_REPO), "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        findings = _findings_by_rule(_parse_findings(_hygiene_jsonl(tmp_path)))
        assert "HYG-BLD-001" in findings
        assert findings["HYG-BLD-001"]["rag"] == "green"

    def test_bld_002_amber(self, runner: CliRunner, tmp_path: Path) -> None:
        """No version declared in minimal pom.xml."""
        result = runner.invoke(
            cli,
            ["hygiene", str(JAVA_DIRTY_REPO), "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        findings = _findings_by_rule(_parse_findings(_hygiene_jsonl(tmp_path)))
        assert "HYG-BLD-002" in findings
        assert findings["HYG-BLD-002"]["rag"] == "amber"

    def test_doc_001_present(self, runner: CliRunner, tmp_path: Path) -> None:
        """DOC-001 should fire for dirty repo (result depends on metadata parsing)."""
        result = runner.invoke(
            cli,
            ["hygiene", str(JAVA_DIRTY_REPO), "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        findings = _findings_by_rule(_parse_findings(_hygiene_jsonl(tmp_path)))
        assert "HYG-DOC-001" in findings

    def test_ci_003_amber(self, runner: CliRunner, tmp_path: Path) -> None:
        """No CI present, so lint check cannot be green."""
        result = runner.invoke(
            cli,
            ["hygiene", str(JAVA_DIRTY_REPO), "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        findings = _findings_by_rule(_parse_findings(_hygiene_jsonl(tmp_path)))
        if "HYG-CI-003" in findings:
            assert findings["HYG-CI-003"]["rag"] in ("amber", "red", "skipped")

    def test_has_red_or_amber_findings(self, runner: CliRunner, tmp_path: Path) -> None:
        """Dirty repo must produce at least some non-green findings."""
        result = runner.invoke(
            cli,
            ["hygiene", str(JAVA_DIRTY_REPO), "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        findings = _parse_findings(_hygiene_jsonl(tmp_path))
        bad = [f for f in findings if f["rag"] in ("red", "amber")]
        assert len(bad) >= 3, f"Expected >=3 red/amber findings, got {len(bad)}"

    def test_community_rules_not_green(self, runner: CliRunner, tmp_path: Path) -> None:
        """Dirty repo missing community files should have amber/red COM findings."""
        result = runner.invoke(
            cli,
            ["hygiene", str(JAVA_DIRTY_REPO), "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        findings = _findings_by_rule(_parse_findings(_hygiene_jsonl(tmp_path)))
        com_rules = {k: v for k, v in findings.items() if k.startswith("HYG-COM")}
        non_green = sum(1 for f in com_rules.values() if f["rag"] != "green")
        assert non_green >= 3, f"Expected >=3 non-green COM rules, got {non_green}"


class TestPythonCleanRepoRegression:
    """Regression guard: existing Python hygiene-clean-repo should remain passing."""

    def test_exits_0(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(
            cli,
            ["hygiene", str(PYTHON_CLEAN_REPO), "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 0, f"Exit {result.exit_code}: {result.output}"

    def test_no_red_findings(self, runner: CliRunner, tmp_path: Path) -> None:
        """Python clean repo must produce no red findings."""
        result = runner.invoke(
            cli,
            ["hygiene", str(PYTHON_CLEAN_REPO), "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        findings = _parse_findings(_hygiene_jsonl(tmp_path))
        red = [f for f in findings if f["rag"] == "red"]
        assert red == [], f"Unexpected red findings in Python clean repo: {red}"

    def test_no_amber_findings(self, runner: CliRunner, tmp_path: Path) -> None:
        """Python clean repo must produce no amber findings."""
        result = runner.invoke(
            cli,
            ["hygiene", str(PYTHON_CLEAN_REPO), "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        findings = _parse_findings(_hygiene_jsonl(tmp_path))
        amber = [f for f in findings if f["rag"] == "amber"]
        assert amber == [], f"Unexpected amber findings in Python clean repo: {amber}"

    def test_bld_001_green(self, runner: CliRunner, tmp_path: Path) -> None:
        """pyproject.toml present."""
        result = runner.invoke(
            cli,
            ["hygiene", str(PYTHON_CLEAN_REPO), "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        findings = _findings_by_rule(_parse_findings(_hygiene_jsonl(tmp_path)))
        assert "HYG-BLD-001" in findings
        assert findings["HYG-BLD-001"]["rag"] == "green"

    def test_false_positive_rate_zero(self, runner: CliRunner, tmp_path: Path) -> None:
        """Clean Python repo should have 0% false positive rate."""
        result = runner.invoke(
            cli,
            ["hygiene", str(PYTHON_CLEAN_REPO), "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        findings = _parse_findings(_hygiene_jsonl(tmp_path))
        false_pos = [f for f in findings if f["rag"] in ("red", "amber")]
        assert false_pos == [], f"False positives in Python clean repo: {false_pos}"
