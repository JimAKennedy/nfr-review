"""Tests for code-debt collector and HYG-BLD-005 rule."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nfr_review.hygiene import hygiene_collector_registry, hygiene_rule_registry
from nfr_review.hygiene.collectors.code_debt import CodeDebtCollector
from nfr_review.hygiene.rules.bld_code_debt import CodeDebtRule
from nfr_review.models import Evidence

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_evidence(payload: dict[str, Any]) -> list[Evidence]:
    return [
        Evidence(
            collector_name="code-debt",
            collector_version="0.1.0",
            locator=".",
            kind="code-debt-analysis",
            payload=payload,
        )
    ]


# ---------------------------------------------------------------------------
# Collector Registration
# ---------------------------------------------------------------------------


class TestCodeDebtRegistration:
    def test_collector_registered(self) -> None:
        assert "code-debt" in hygiene_collector_registry

    def test_collector_name(self) -> None:
        assert CodeDebtCollector.name == "code-debt"


# ---------------------------------------------------------------------------
# Collector Behaviour
# ---------------------------------------------------------------------------


class TestCodeDebtCollector:
    def test_empty_repo(self, tmp_path: Path) -> None:
        c = CodeDebtCollector()
        ev_list = c.collect(tmp_path, config=None)
        assert len(ev_list) == 1
        assert ev_list[0].kind == "code-debt-analysis"
        assert ev_list[0].payload["total_markers"] == 0

    def test_single_todo(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text("# TODO fix this\nx = 1\n")
        c = CodeDebtCollector()
        ev_list = c.collect(tmp_path, config=None)
        p = ev_list[0].payload
        assert p["total_markers"] == 1
        assert p["per_marker"]["TODO"] == 1

    def test_multiple_markers(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text(
            "# TODO item one\n# FIXME broken\n# HACK bypass\n# XXX danger\n"
        )
        c = CodeDebtCollector()
        ev_list = c.collect(tmp_path, config=None)
        p = ev_list[0].payload
        assert p["total_markers"] == 4
        assert p["per_marker"]["TODO"] == 1
        assert p["per_marker"]["FIXME"] == 1
        assert p["per_marker"]["HACK"] == 1
        assert p["per_marker"]["XXX"] == 1

    def test_case_insensitive(self, tmp_path: Path) -> None:
        (tmp_path / "code.py").write_text("# todo lower\n# Todo mixed\n# TODO upper\n")
        c = CodeDebtCollector()
        ev_list = c.collect(tmp_path, config=None)
        p = ev_list[0].payload
        assert p["per_marker"]["TODO"] == 3

    def test_skips_node_modules(self, tmp_path: Path) -> None:
        nm = tmp_path / "node_modules" / "pkg"
        nm.mkdir(parents=True)
        (nm / "index.js").write_text("// TODO vendor code\n")
        (tmp_path / "app.py").write_text("# TODO real code\n")
        c = CodeDebtCollector()
        ev_list = c.collect(tmp_path, config=None)
        p = ev_list[0].payload
        assert p["total_markers"] == 1

    def test_skips_git_dir(self, tmp_path: Path) -> None:
        git = tmp_path / ".git"
        git.mkdir()
        (git / "config").write_text("# TODO internal\n")
        c = CodeDebtCollector()
        ev_list = c.collect(tmp_path, config=None)
        assert ev_list[0].payload["total_markers"] == 0

    def test_skips_non_source_files(self, tmp_path: Path) -> None:
        (tmp_path / "image.png").write_bytes(b"\x89PNG TODO fake")
        (tmp_path / "data.csv").write_text("TODO,col2\n")
        c = CodeDebtCollector()
        ev_list = c.collect(tmp_path, config=None)
        assert ev_list[0].payload["total_markers"] == 0

    def test_top_files_sorted_by_count(self, tmp_path: Path) -> None:
        (tmp_path / "few.py").write_text("# TODO one\n")
        (tmp_path / "many.py").write_text("# TODO a\n# TODO b\n# TODO c\n# FIXME d\n")
        c = CodeDebtCollector()
        ev_list = c.collect(tmp_path, config=None)
        p = ev_list[0].payload
        assert p["top_files"][0]["path"] == "many.py"
        assert p["top_files"][0]["count"] == 4

    def test_file_count(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("# TODO\n")
        (tmp_path / "b.py").write_text("# FIXME\n")
        (tmp_path / "clean.py").write_text("# no markers\n")
        c = CodeDebtCollector()
        ev_list = c.collect(tmp_path, config=None)
        assert ev_list[0].payload["file_count"] == 2

    def test_workaround_marker(self, tmp_path: Path) -> None:
        (tmp_path / "fix.py").write_text("# WORKAROUND for bug #123\n")
        c = CodeDebtCollector()
        ev_list = c.collect(tmp_path, config=None)
        assert ev_list[0].payload["per_marker"]["WORKAROUND"] == 1

    def test_temp_marker(self, tmp_path: Path) -> None:
        (tmp_path / "tmp.py").write_text("# TEMP until refactor\n# also TEMP here\n")
        c = CodeDebtCollector()
        ev_list = c.collect(tmp_path, config=None)
        p = ev_list[0].payload
        assert p["per_marker"]["TEMP"] == 2

    def test_multiple_source_types(self, tmp_path: Path) -> None:
        (tmp_path / "app.java").write_text("// TODO java marker\n")
        (tmp_path / "main.go").write_text("// FIXME go marker\n")
        (tmp_path / "lib.rs").write_text("// HACK rust marker\n")
        c = CodeDebtCollector()
        ev_list = c.collect(tmp_path, config=None)
        assert ev_list[0].payload["total_markers"] == 3


# ---------------------------------------------------------------------------
# HYG-BLD-005: Code Debt Threshold Rule
# ---------------------------------------------------------------------------


class TestCodeDebtRule:
    def test_rule_registered(self) -> None:
        assert "HYG-BLD-005" in hygiene_rule_registry

    def test_rule_metadata(self) -> None:
        assert CodeDebtRule.id == "HYG-BLD-005"
        assert CodeDebtRule.category == "build-readiness"
        assert CodeDebtRule.band == 1
        assert CodeDebtRule.required_collectors == ["code-debt"]

    def test_skip_when_no_evidence(self) -> None:
        rule = CodeDebtRule()
        result = rule.evaluate([], context=None)
        assert result.skipped

    def test_green_when_no_markers(self) -> None:
        rule = CodeDebtRule()
        payload = {"total_markers": 0, "per_marker": {}, "file_count": 0, "top_files": []}
        result = rule.evaluate(_make_evidence(payload), context=None)
        assert result.findings[0].rag == "green"
        assert "No code debt markers" in result.findings[0].summary

    def test_green_when_below_threshold(self) -> None:
        rule = CodeDebtRule()
        payload = {
            "total_markers": 5,
            "per_marker": {"TODO": 3, "FIXME": 2},
            "file_count": 2,
            "top_files": [{"path": "a.py", "count": 3, "markers": {"TODO": 3}}],
        }
        result = rule.evaluate(_make_evidence(payload), context=None)
        assert result.findings[0].rag == "green"
        assert "within threshold" in result.findings[0].summary

    def test_green_at_threshold(self) -> None:
        rule = CodeDebtRule()
        payload = {
            "total_markers": 20,
            "per_marker": {"TODO": 20},
            "file_count": 5,
            "top_files": [],
        }
        result = rule.evaluate(_make_evidence(payload), context=None)
        assert result.findings[0].rag == "green"

    def test_amber_above_threshold(self) -> None:
        rule = CodeDebtRule()
        payload = {
            "total_markers": 25,
            "per_marker": {"TODO": 15, "FIXME": 10},
            "file_count": 8,
            "top_files": [
                {"path": "big.py", "count": 10, "markers": {"TODO": 10}},
                {"path": "med.py", "count": 5, "markers": {"FIXME": 5}},
            ],
        }
        result = rule.evaluate(_make_evidence(payload), context=None)
        assert result.findings[0].rag == "amber"
        assert result.findings[0].severity == "low"
        assert "exceeds threshold" in result.findings[0].summary

    def test_amber_recommendation_lists_top_files(self) -> None:
        rule = CodeDebtRule()
        payload = {
            "total_markers": 30,
            "per_marker": {"TODO": 30},
            "file_count": 3,
            "top_files": [
                {"path": "worst.py", "count": 20, "markers": {"TODO": 20}},
                {"path": "bad.py", "count": 10, "markers": {"TODO": 10}},
            ],
        }
        result = rule.evaluate(_make_evidence(payload), context=None)
        assert "worst.py" in result.findings[0].recommendation

    def test_finding_pattern_tag(self) -> None:
        rule = CodeDebtRule()
        payload = {"total_markers": 0, "per_marker": {}, "file_count": 0, "top_files": []}
        result = rule.evaluate(_make_evidence(payload), context=None)
        assert result.findings[0].pattern_tag == "code-debt"

    def test_marker_summary_in_amber(self) -> None:
        rule = CodeDebtRule()
        payload = {
            "total_markers": 25,
            "per_marker": {"HACK": 15, "XXX": 10},
            "file_count": 5,
            "top_files": [],
        }
        result = rule.evaluate(_make_evidence(payload), context=None)
        assert "HACK: 15" in result.findings[0].summary
        assert "XXX: 10" in result.findings[0].summary


# ---------------------------------------------------------------------------
# Integration: Collector → Rule on fixtures
# ---------------------------------------------------------------------------

_FIXTURES = Path(__file__).parent / "fixtures"


class TestCodeDebtIntegration:
    def test_clean_repo_has_no_markers(self) -> None:
        c = CodeDebtCollector()
        ev_list = c.collect(_FIXTURES / "hygiene-clean-repo", config=None)
        assert ev_list[0].payload["total_markers"] == 0

    def test_dirty_repo_has_markers(self) -> None:
        c = CodeDebtCollector()
        ev_list = c.collect(_FIXTURES / "hygiene-dirty-repo", config=None)
        p = ev_list[0].payload
        assert p["total_markers"] >= 4
        assert "TODO" in p["per_marker"]
        assert "FIXME" in p["per_marker"]

    def test_dirty_repo_rule_evaluation(self) -> None:
        c = CodeDebtCollector()
        ev_list = c.collect(_FIXTURES / "hygiene-dirty-repo", config=None)
        rule = CodeDebtRule()
        result = rule.evaluate(ev_list, context=None)
        f = result.findings[0]
        assert f.rule_id == "HYG-BLD-005"
        assert f.rag in ("green", "amber")
