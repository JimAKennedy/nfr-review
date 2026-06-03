"""S05 integration tests — fixtures, dogfood, coexistence, category filtering."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from nfr_review.cli import cli

FIXTURES = Path(__file__).parent / "fixtures"
DIRTY_REPO = FIXTURES / "hygiene-dirty-repo"
CLEAN_REPO = FIXTURES / "hygiene-clean-repo"
REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _hygiene_jsonl(tmp_path: Path) -> Path:
    matches = list(tmp_path.glob("*-hygiene-report.jsonl"))
    assert len(matches) == 1, f"Expected one hygiene JSONL, found {matches}"
    return matches[0]


def _hygiene_csv(tmp_path: Path) -> Path:
    matches = list(tmp_path.glob("*-hygiene-report.csv"))
    assert len(matches) == 1, f"Expected one hygiene CSV, found {matches}"
    return matches[0]


class TestListChecks:
    def test_shows_all_rules(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["hygiene", "--list-checks"])
        assert result.exit_code == 0
        lines = [ln for ln in result.output.splitlines() if ln.strip()]
        assert len(lines) >= 20

    def test_includes_bld_rules(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["hygiene", "--list-checks"])
        assert "HYG-BLD-001" in result.output
        assert "HYG-BLD-002" in result.output
        assert "HYG-BLD-003" in result.output

    def test_includes_prv_rules(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["hygiene", "--list-checks"])
        assert "HYG-PRV-001" in result.output
        assert "HYG-PRV-002" in result.output
        assert "HYG-PRV-003" in result.output

    def test_includes_existing_categories(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["hygiene", "--list-checks"])
        assert "HYG-COM-001" in result.output
        assert "HYG-CI-001" in result.output
        assert "HYG-DOC-001" in result.output


class TestCategoryFiltering:
    def test_build_readiness_only(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(
            cli,
            [
                "hygiene",
                str(DIRTY_REPO),
                "--category",
                "build-readiness",
                "--output-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0
        jsonl = _hygiene_jsonl(tmp_path).read_text()
        assert "HYG-BLD" in jsonl
        assert "HYG-COM" not in jsonl
        assert "HYG-PRV" not in jsonl

    def test_privacy_only(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(
            cli,
            [
                "hygiene",
                str(DIRTY_REPO),
                "--category",
                "privacy",
                "--output-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0
        jsonl = _hygiene_jsonl(tmp_path).read_text()
        assert "HYG-PRV" in jsonl
        assert "HYG-COM" not in jsonl
        assert "HYG-BLD" not in jsonl

    def test_multiple_categories(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(
            cli,
            [
                "hygiene",
                str(DIRTY_REPO),
                "--category",
                "community,ci-automation",
                "--output-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0
        jsonl = _hygiene_jsonl(tmp_path).read_text()
        assert "HYG-COM" in jsonl
        assert "HYG-CI" in jsonl
        assert "HYG-BLD" not in jsonl


class TestDirtyRepoE2E:
    def test_produces_findings_all_categories(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(
            cli,
            ["hygiene", str(DIRTY_REPO), "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        jsonl = _hygiene_jsonl(tmp_path).read_text()
        assert "HYG-COM" in jsonl
        assert "HYG-CI" in jsonl
        assert "HYG-DOC" in jsonl
        assert "HYG-BLD" in jsonl
        assert "HYG-PRV" in jsonl

    def test_has_red_or_amber_findings(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(
            cli,
            ["hygiene", str(DIRTY_REPO), "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        jsonl = _hygiene_jsonl(tmp_path).read_text()
        assert '"red"' in jsonl or '"amber"' in jsonl


class TestCleanRepoE2E:
    def test_only_green_or_info_findings(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(
            cli,
            ["hygiene", str(CLEAN_REPO), "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 0, f"Exit {result.exit_code}: {result.output}"
        jsonl = _hygiene_jsonl(tmp_path).read_text()
        assert '"red"' not in jsonl
        assert '"amber"' not in jsonl

    def test_false_positive_rate_under_5_pct(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(
            cli,
            ["hygiene", str(CLEAN_REPO), "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        jsonl = _hygiene_jsonl(tmp_path).read_text()
        lines = [ln for ln in jsonl.splitlines() if ln.strip()]
        total = len(lines)
        false_positives = sum(1 for ln in lines if '"red"' in ln or '"amber"' in ln)
        if total > 0:
            rate = false_positives / total
            assert rate < 0.05, f"False positive rate {rate:.1%} >= 5%"


class TestDogfood:
    @pytest.mark.timeout(300)
    def test_nfr_review_repo_exits_0(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(
            cli,
            ["hygiene", str(REPO_ROOT), "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 0, f"Exit {result.exit_code}: {result.output}"

    def test_nfr_review_non_privacy_categories_no_red(
        self,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        result = runner.invoke(
            cli,
            [
                "hygiene",
                str(REPO_ROOT),
                "--output-dir",
                str(tmp_path),
                "--category",
                "community,ci-automation,documentation,build-readiness",
            ],
        )
        assert result.exit_code == 0
        jsonl = _hygiene_jsonl(tmp_path).read_text()
        assert '"red"' not in jsonl, f"Red findings in non-privacy dogfood:\n{jsonl}"

    def test_nfr_review_source_files_no_pii(
        self,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """Privacy scanner hits test fixtures and .gsd/ files (expected).
        Verify that src/ files themselves produce no red findings."""
        result = runner.invoke(
            cli,
            [
                "hygiene",
                str(REPO_ROOT),
                "--output-dir",
                str(tmp_path),
                "--category",
                "privacy",
            ],
        )
        assert result.exit_code == 0
        src_red = []
        for line in _hygiene_jsonl(tmp_path).read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("record_type") != "finding":
                continue
            loc = rec.get("evidence_locator", "")
            if rec.get("rag") == "red" and loc.startswith("src/"):
                src_red.append(rec)
        assert src_red == [], f"Red privacy findings in src/: {src_red}"


class TestCoexistence:
    def test_run_and_hygiene_no_collision(self, runner: CliRunner, tmp_path: Path) -> None:
        target = CLEAN_REPO
        run_result = runner.invoke(
            cli,
            [
                "run",
                str(target),
                "--csv",
                str(tmp_path / "nfr-review.csv"),
                "--jsonl",
                str(tmp_path / "nfr-review.jsonl"),
            ],
        )
        assert run_result.exit_code == 0, (
            f"run exit {run_result.exit_code}: {run_result.output}"
        )

        hyg_result = runner.invoke(
            cli,
            ["hygiene", str(target), "--output-dir", str(tmp_path)],
        )
        assert hyg_result.exit_code == 0, (
            f"hygiene exit {hyg_result.exit_code}: {hyg_result.output}"
        )

        assert (tmp_path / "nfr-review.csv").exists()
        assert (tmp_path / "nfr-review.jsonl").exists()
        assert _hygiene_csv(tmp_path).exists()
        assert _hygiene_jsonl(tmp_path).exists()

        nfr_content = (tmp_path / "nfr-review.jsonl").read_text()
        hyg_content = _hygiene_jsonl(tmp_path).read_text()
        assert nfr_content != hyg_content


class TestSeverityThreshold:
    def test_dirty_exits_2_with_high_threshold(
        self,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        result = runner.invoke(
            cli,
            [
                "hygiene",
                str(DIRTY_REPO),
                "--severity-threshold",
                "high",
                "--output-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 2, (
            f"Expected exit 2, got {result.exit_code}: {result.output}"
        )

    def test_clean_exits_0_with_high_threshold(
        self,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        result = runner.invoke(
            cli,
            [
                "hygiene",
                str(CLEAN_REPO),
                "--severity-threshold",
                "high",
                "--output-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0, (
            f"Expected exit 0, got {result.exit_code}: {result.output}"
        )
