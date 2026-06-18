# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.design_change.diff import (
    CategoryDiff,
    NumericDelta,
    SetDelta,
    diff_baselines,
    format_diff_summary,
)
from nfr_review.design_change.extractors import (
    MetricExtractor,
    build_baseline,
    extract_all_metrics,
)
from nfr_review.design_change.models import (
    BASELINE_FORMAT_VERSION,
    MetricCategory,
    NumericMetric,
    SetMetric,
    StructuralBaseline,
)
from nfr_review.design_change.snapshot import load_baseline, save_baseline
from nfr_review.models import Evidence
from nfr_review.registry import Registry


def _make_baseline(
    metrics: dict[str, MetricCategory] | None = None,
    source_repo: str = "/tmp/test-repo",
) -> StructuralBaseline:
    return StructuralBaseline(
        source_repo=source_repo,
        metrics=metrics or {},
    )


def _make_category(
    name: str,
    numeric: dict[str, float] | None = None,
    sets: dict[str, list[str]] | None = None,
) -> MetricCategory:
    nm = {k: NumericMetric(name=k, value=v) for k, v in (numeric or {}).items()}
    sm = {k: SetMetric(name=k, items=v) for k, v in (sets or {}).items()}
    return MetricCategory(category=name, numeric_metrics=nm, set_metrics=sm)


class TestStructuralBaselineRoundTrip:
    def test_save_load_round_trip(self, tmp_path: Path) -> None:
        cat = _make_category("structure", numeric={"class_count": 42.0})
        baseline = _make_baseline(metrics={"structure": cat})

        path = tmp_path / "baseline.json"
        save_baseline(baseline, path)
        loaded = load_baseline(path)

        assert loaded.version == baseline.version
        assert loaded.source_repo == baseline.source_repo
        assert loaded.created_at == baseline.created_at
        assert "structure" in loaded.metrics
        assert loaded.metrics["structure"].numeric_metrics["class_count"].value == 42.0

    def test_load_rejects_future_version(self, tmp_path: Path) -> None:
        cat = _make_category("x")
        baseline = _make_baseline(metrics={"x": cat})
        path = tmp_path / "baseline.json"
        save_baseline(baseline, path)

        import json

        data = json.loads(path.read_text())
        data["version"] = BASELINE_FORMAT_VERSION + 1
        path.write_text(json.dumps(data))

        with pytest.raises(ValueError, match="unsupported structural baseline version"):
            load_baseline(path)

    def test_load_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="structural baseline file not found"):
            load_baseline(tmp_path / "nonexistent.json")


class TestNumericDiff:
    def test_numeric_metrics_produce_correct_deltas(self) -> None:
        prev = _make_baseline(
            metrics={"structure": _make_category("structure", numeric={"class_count": 100.0})}
        )
        curr = _make_baseline(
            metrics={"structure": _make_category("structure", numeric={"class_count": 130.0})}
        )

        diffs = diff_baselines(prev, curr)
        assert "structure" in diffs
        nd = diffs["structure"].numeric_deltas[0]
        assert nd.name == "class_count"
        assert nd.old_value == 100.0
        assert nd.new_value == 130.0
        assert nd.delta == 30.0
        assert nd.pct_change == pytest.approx(30.0)

    def test_zero_base_has_no_pct(self) -> None:
        prev = _make_baseline(metrics={"m": _make_category("m", numeric={"x": 0.0})})
        curr = _make_baseline(metrics={"m": _make_category("m", numeric={"x": 5.0})})
        diffs = diff_baselines(prev, curr)
        nd = diffs["m"].numeric_deltas[0]
        assert nd.pct_change is None


class TestSetDiff:
    def test_set_metrics_produce_correct_added_removed(self) -> None:
        prev = _make_baseline(
            metrics={
                "deps": _make_category("deps", sets={"dependencies": ["spring-core", "guava"]})
            }
        )
        curr = _make_baseline(
            metrics={
                "deps": _make_category(
                    "deps", sets={"dependencies": ["spring-core", "lombok"]}
                )
            }
        )

        diffs = diff_baselines(prev, curr)
        assert "deps" in diffs
        sd = diffs["deps"].set_deltas[0]
        assert sd.name == "dependencies"
        assert sd.added == ["lombok"]
        assert sd.removed == ["guava"]


class TestNoChanges:
    def test_identical_baselines_produce_empty_diff(self) -> None:
        cat = _make_category("structure", numeric={"class_count": 42.0})
        bl = _make_baseline(metrics={"structure": cat})
        diffs = diff_baselines(bl, bl)
        assert diffs == {}


class TestFormatDiffSummary:
    def test_empty_diff_produces_no_changes_message(self) -> None:
        assert format_diff_summary({}) == "No structural changes detected."

    def test_summary_includes_category_and_values(self) -> None:
        diffs = {
            "structure": CategoryDiff(
                category="structure",
                numeric_deltas=[
                    NumericDelta(
                        name="class_count",
                        old_value=100,
                        new_value=130,
                        delta=30,
                        pct_change=30.0,
                    )
                ],
            ),
        }
        summary = format_diff_summary(diffs)
        assert "[structure]" in summary
        assert "class_count" in summary
        assert "100 -> 130" in summary
        assert "+30.0%" in summary

    def test_summary_includes_set_changes(self) -> None:
        diffs = {
            "deps": CategoryDiff(
                category="deps",
                set_deltas=[
                    SetDelta(name="dependencies", added=["lombok"], removed=["guava"]),
                ],
            ),
        }
        summary = format_diff_summary(diffs)
        assert "dependencies added: lombok" in summary
        assert "dependencies removed: guava" in summary


class _DummyExtractor:
    @property
    def category(self) -> str:
        return "test_category"

    def extract(self, evidence: list[Evidence]) -> MetricCategory:
        return MetricCategory(
            category="test_category",
            numeric_metrics={
                "evidence_count": NumericMetric(
                    name="evidence_count", value=float(len(evidence))
                )
            },
        )


class TestExtractorRegistry:
    def test_register_and_extract(self) -> None:
        reg: Registry[MetricExtractor] = Registry("test_extractor")
        ext = _DummyExtractor()
        reg.register("test", ext)

        evidence = [
            Evidence(
                collector_name="test",
                collector_version="1.0",
                locator="/foo",
                kind="test",
            ),
            Evidence(
                collector_name="test",
                collector_version="1.0",
                locator="/bar",
                kind="test",
            ),
        ]

        result = extract_all_metrics(evidence, registry=reg)
        assert "test_category" in result
        assert result["test_category"].numeric_metrics["evidence_count"].value == 2.0


class TestBuildBaseline:
    def test_metadata_populated(self) -> None:
        reg: Registry[MetricExtractor] = Registry("test_extractor")
        ext = _DummyExtractor()
        reg.register("test", ext)

        bl = build_baseline([], "/tmp/my-repo", registry=reg)
        assert bl.source_repo == "/tmp/my-repo"
        assert bl.version == BASELINE_FORMAT_VERSION
        assert bl.created_at  # non-empty
        assert "test_category" in bl.metrics


class TestApplyThresholds:
    def test_filters_numeric_below_threshold(self) -> None:
        from nfr_review.design_change.diff import apply_thresholds

        diffs = {
            "structure": CategoryDiff(
                category="structure",
                numeric_deltas=[
                    NumericDelta(
                        name="class_count",
                        old_value=100,
                        new_value=110,
                        delta=10,
                        pct_change=10.0,
                    )
                ],
            ),
        }
        result = apply_thresholds(diffs, {"class_count": 20.0})
        assert result == {}

    def test_passes_numeric_above_threshold(self) -> None:
        from nfr_review.design_change.diff import apply_thresholds

        diffs = {
            "structure": CategoryDiff(
                category="structure",
                numeric_deltas=[
                    NumericDelta(
                        name="class_count",
                        old_value=100,
                        new_value=130,
                        delta=30,
                        pct_change=30.0,
                    )
                ],
            ),
        }
        result = apply_thresholds(diffs, {"class_count": 20.0})
        assert "structure" in result
        assert len(result["structure"].numeric_deltas) == 1

    def test_passes_numeric_with_no_pct_change(self) -> None:
        from nfr_review.design_change.diff import apply_thresholds

        diffs = {
            "m": CategoryDiff(
                category="m",
                numeric_deltas=[
                    NumericDelta(
                        name="class_count",
                        old_value=0,
                        new_value=5,
                        delta=5,
                        pct_change=None,
                    )
                ],
            ),
        }
        result = apply_thresholds(diffs, {"class_count": 20.0})
        assert "m" in result

    def test_passes_metric_without_threshold(self) -> None:
        from nfr_review.design_change.diff import apply_thresholds

        diffs = {
            "structure": CategoryDiff(
                category="structure",
                numeric_deltas=[
                    NumericDelta(
                        name="unknown_metric",
                        old_value=100,
                        new_value=101,
                        delta=1,
                        pct_change=1.0,
                    )
                ],
            ),
        }
        result = apply_thresholds(diffs, {"class_count": 20.0})
        assert "structure" in result

    def test_filters_set_below_threshold(self) -> None:
        from nfr_review.design_change.diff import apply_thresholds

        diffs = {
            "deps": CategoryDiff(
                category="deps",
                set_deltas=[
                    SetDelta(name="adr_count", added=["adr1"], removed=[]),
                ],
            ),
        }
        result = apply_thresholds(diffs, {"adr_count": 2.0})
        assert result == {}

    def test_passes_set_above_threshold(self) -> None:
        from nfr_review.design_change.diff import apply_thresholds

        diffs = {
            "deps": CategoryDiff(
                category="deps",
                set_deltas=[
                    SetDelta(name="adr_count", added=["adr1", "adr2"], removed=["adr3"]),
                ],
            ),
        }
        result = apply_thresholds(diffs, {"adr_count": 2.0})
        assert "deps" in result

    def test_empty_thresholds_passes_all(self) -> None:
        from nfr_review.design_change.diff import apply_thresholds

        diffs = {
            "structure": CategoryDiff(
                category="structure",
                numeric_deltas=[
                    NumericDelta(
                        name="class_count",
                        old_value=100,
                        new_value=101,
                        delta=1,
                        pct_change=1.0,
                    )
                ],
            ),
        }
        result = apply_thresholds(diffs, {})
        assert "structure" in result

    def test_mixed_filtering(self) -> None:
        from nfr_review.design_change.diff import apply_thresholds

        diffs = {
            "structure": CategoryDiff(
                category="structure",
                numeric_deltas=[
                    NumericDelta(
                        name="class_count",
                        old_value=100,
                        new_value=105,
                        delta=5,
                        pct_change=5.0,
                    ),
                    NumericDelta(
                        name="test_coverage",
                        old_value=80,
                        new_value=70,
                        delta=-10,
                        pct_change=-12.5,
                    ),
                ],
            ),
        }
        result = apply_thresholds(diffs, {"class_count": 20.0, "test_coverage": 5.0})
        assert "structure" in result
        assert len(result["structure"].numeric_deltas) == 1
        assert result["structure"].numeric_deltas[0].name == "test_coverage"


class TestCLIDesignBaselineRoundTrip:
    def test_cli_saves_and_diffs_baseline(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        from nfr_review.cli import cli

        fixture = Path(__file__).parent / "fixtures" / "ci-sample-repo"
        if not fixture.exists():
            pytest.skip("ci-sample-repo fixture not available")

        baseline_dir = tmp_path / "baselines"
        runner = CliRunner()

        result1 = runner.invoke(
            cli,
            ["run", str(fixture), "--design-baseline-dir", str(baseline_dir)],
            catch_exceptions=False,
        )
        assert result1.exit_code == 0, result1.output + result1.stderr
        assert "structural baseline" in result1.stderr.lower()

        bl_files = list(baseline_dir.glob("*-structural-baseline.json"))
        assert len(bl_files) == 1

        result2 = runner.invoke(
            cli,
            ["run", str(fixture), "--design-baseline-dir", str(baseline_dir)],
            catch_exceptions=False,
        )
        assert result2.exit_code == 0, result2.output + result2.stderr
        assert "No structural changes" in result2.stderr
