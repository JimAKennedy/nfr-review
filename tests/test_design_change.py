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


class TestStructuralSignalsDiff:
    """S03 demo criterion: diff two baselines where fixture B has 30% more classes,
    a new JDepend cycle, and 6 new dormant classes — all three signals fire."""

    def test_class_count_delta_fires(self) -> None:
        from nfr_review.design_change.diff import apply_thresholds

        prev = _make_baseline(
            metrics={"structure": _make_category("structure", numeric={"class_count": 100.0})}
        )
        curr = _make_baseline(
            metrics={"structure": _make_category("structure", numeric={"class_count": 130.0})}
        )

        diffs = diff_baselines(prev, curr)
        result = apply_thresholds(diffs, {"class_count": 20.0})

        assert "structure" in result
        nd = result["structure"].numeric_deltas[0]
        assert nd.name == "class_count"
        assert nd.pct_change == pytest.approx(30.0)
        assert nd.pct_change > 20.0

    def test_jdepend_cycle_introduced_fires(self) -> None:
        prev = _make_baseline(
            metrics={"jdepend": _make_category("jdepend", sets={"jdepend_cycles": []})}
        )
        curr = _make_baseline(
            metrics={
                "jdepend": _make_category(
                    "jdepend",
                    sets={"jdepend_cycles": ["com.example.a", "com.example.b"]},
                )
            }
        )

        diffs = diff_baselines(prev, curr)

        assert "jdepend" in diffs
        sd = diffs["jdepend"].set_deltas[0]
        assert sd.name == "jdepend_cycles"
        assert sorted(sd.added) == ["com.example.a", "com.example.b"]
        assert sd.removed == []

    def test_dormant_class_explosion_fires(self) -> None:
        from nfr_review.design_change.diff import apply_thresholds

        prev = _make_baseline(
            metrics={
                "structure": _make_category("structure", numeric={"dormant_class_count": 2.0})
            }
        )
        curr = _make_baseline(
            metrics={
                "structure": _make_category("structure", numeric={"dormant_class_count": 8.0})
            }
        )

        diffs = diff_baselines(prev, curr)
        result = apply_thresholds(diffs, {"dormant_class_count": 25.0})

        assert "structure" in result
        nd = result["structure"].numeric_deltas[0]
        assert nd.name == "dormant_class_count"
        assert nd.pct_change == pytest.approx(300.0)
        assert nd.pct_change > 25.0

    def test_all_three_signals_fire_together(self) -> None:
        from nfr_review.config import DEFAULT_DESIGN_CHANGE_THRESHOLDS
        from nfr_review.design_change.diff import apply_thresholds

        prev = _make_baseline(
            metrics={
                "structure": _make_category(
                    "structure",
                    numeric={"class_count": 100.0, "dormant_class_count": 2.0},
                ),
                "jdepend": _make_category("jdepend", sets={"jdepend_cycles": []}),
            }
        )
        curr = _make_baseline(
            metrics={
                "structure": _make_category(
                    "structure",
                    numeric={"class_count": 130.0, "dormant_class_count": 8.0},
                ),
                "jdepend": _make_category(
                    "jdepend",
                    sets={"jdepend_cycles": ["com.example.a", "com.example.b"]},
                ),
            }
        )

        diffs = diff_baselines(prev, curr)
        result = apply_thresholds(diffs, DEFAULT_DESIGN_CHANGE_THRESHOLDS)

        # class_count: 30% > 20% threshold
        assert "structure" in result
        structure_numeric_names = {nd.name for nd in result["structure"].numeric_deltas}
        assert "class_count" in structure_numeric_names

        # dormant_class_count: 300% > 25% threshold
        assert "dormant_class_count" in structure_numeric_names

        # jdepend_cycles: 2 added > 0 (no threshold means passes through)
        assert "jdepend" in result
        set_names = {sd.name for sd in result["jdepend"].set_deltas}
        assert "jdepend_cycles" in set_names

    def test_below_threshold_filtered(self) -> None:
        from nfr_review.design_change.diff import apply_thresholds

        prev = _make_baseline(
            metrics={"structure": _make_category("structure", numeric={"class_count": 100.0})}
        )
        curr = _make_baseline(
            metrics={"structure": _make_category("structure", numeric={"class_count": 105.0})}
        )

        diffs = diff_baselines(prev, curr)
        result = apply_thresholds(diffs, {"class_count": 20.0})

        assert result == {}

    def test_jdepend_instability_spike(self) -> None:
        from nfr_review.design_change.diff import apply_thresholds

        prev = _make_baseline(
            metrics={
                "jdepend": _make_category("jdepend", numeric={"jdepend_instability": 0.5})
            }
        )
        curr = _make_baseline(
            metrics={
                "jdepend": _make_category("jdepend", numeric={"jdepend_instability": 0.7})
            }
        )

        diffs = diff_baselines(prev, curr)
        result = apply_thresholds(diffs, {"jdepend_instability": 15.0})

        assert "jdepend" in result
        nd = result["jdepend"].numeric_deltas[0]
        assert nd.name == "jdepend_instability"
        assert nd.pct_change == pytest.approx(40.0)
        assert nd.pct_change > 15.0


class TestStructuralExtractors:
    """Tests that verify extractors work with typed payload evidence."""

    def test_structural_extractor_counts_classes(self) -> None:
        from nfr_review.collectors.payloads.java_ast import (
            JavaAstFilePayload,
            JavaBaseClass,
            JavaClass,
        )
        from nfr_review.design_change.structural_signals import StructuralMetricsExtractor

        def _make_java_class(name: str) -> JavaClass:
            return JavaClass(
                name=name,
                line=1,
                annotations=[],
                is_abstract=False,
                is_interface=False,
                base_classes=[],
                fields=[],
                methods=[],
                namespace="com.example",
                outer_class="",
            )

        # Two classes: OrderService extends BaseService, so they are connected.
        # A third class Orphan has no connections — it is dormant.
        base_class_ref = JavaBaseClass(name="BaseService", access="public")
        order_service = JavaClass(
            name="OrderService",
            line=1,
            annotations=[],
            is_abstract=False,
            is_interface=False,
            base_classes=[base_class_ref],
            fields=[],
            methods=[],
            namespace="com.example",
            outer_class="",
        )
        base_service = _make_java_class("BaseService")
        orphan = _make_java_class("Orphan")

        payload = JavaAstFilePayload(
            file_path="/src/main/OrderService.java",
            package="com.example",
            classes=[order_service, base_service, orphan],
            methods=[],
            catch_blocks=[],
            imports=[],
            thread_pool_constructions=[],
            log_statements=[],
        )

        ev = Evidence(
            collector_name="java-ast",
            collector_version="0.1.0",
            locator="/test",
            kind="java-ast-file",
            payload=payload,
        )

        extractor = StructuralMetricsExtractor()
        category = extractor.extract([ev])

        assert category.category == "structure"
        assert "class_count" in category.numeric_metrics
        assert category.numeric_metrics["class_count"].value == 3.0
        assert "dormant_class_count" in category.numeric_metrics
        # Orphan is disconnected; OrderService and BaseService are connected.
        assert category.numeric_metrics["dormant_class_count"].value == 1.0

    def test_jdepend_extractor_extracts_instability(self) -> None:
        from nfr_review.collectors.payloads.jdepend import (
            JDependPackageMetrics,
            JDependPackagesPayload,
        )
        from nfr_review.design_change.structural_signals import JDependMetricsExtractor

        pkg_low = JDependPackageMetrics(name="com.example.core", i=0.3)
        pkg_high = JDependPackageMetrics(name="com.example.service", i=0.85)

        payload = JDependPackagesPayload(
            bytecode_dir="/build/classes",
            packages=[pkg_low, pkg_high],
        )

        ev = Evidence(
            collector_name="jdepend",
            collector_version="0.1.0",
            locator="/test",
            kind="jdepend-packages",
            payload=payload,
        )

        extractor = JDependMetricsExtractor()
        category = extractor.extract([ev])

        assert category.category == "jdepend"
        assert "jdepend_instability" in category.numeric_metrics
        # Extractor should record the max instability across packages.
        assert category.numeric_metrics["jdepend_instability"].value == pytest.approx(0.85)


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


class TestDependencyMetricsExtractor:
    """Tests for the DependencyMetricsExtractor."""

    def test_extracts_dependency_count_and_names(self) -> None:
        from nfr_review.collectors.payloads.deps import DependencyItem, DepsPayload
        from nfr_review.design_change.dependency_coverage_signals import (
            DependencyMetricsExtractor,
        )

        deps = [
            DependencyItem(
                name=f"dep-{i}",
                declared_version="1.0",
                version_constraint="^1.0",
                source_file="pom.xml",
            )
            for i in range(5)
        ]
        payload = DepsPayload(
            dependencies=deps,
            manifest_files_found=["pom.xml"],
            enrichment_errors=[],
        )
        ev = Evidence(
            collector_name="java-deps",
            collector_version="0.1.0",
            locator="/test",
            kind="java-deps",
            payload=payload,
        )

        extractor = DependencyMetricsExtractor()
        category = extractor.extract([ev])

        assert category.category == "dependencies"
        assert category.numeric_metrics["dependency_count"].value == 5.0
        assert len(category.set_metrics["dependency_names"].items) == 5

    def test_skips_indirect_dependencies(self) -> None:
        from nfr_review.collectors.payloads.deps import DependencyItem, DepsPayload
        from nfr_review.design_change.dependency_coverage_signals import (
            DependencyMetricsExtractor,
        )

        deps = [
            DependencyItem(
                name="direct-dep",
                declared_version="1.0",
                version_constraint="^1.0",
                source_file="go.mod",
                indirect=False,
            ),
            DependencyItem(
                name="indirect-dep",
                declared_version="2.0",
                version_constraint="^2.0",
                source_file="go.mod",
                indirect=True,
            ),
        ]
        payload = DepsPayload(
            dependencies=deps,
            manifest_files_found=["go.mod"],
            enrichment_errors=[],
        )
        ev = Evidence(
            collector_name="go-deps",
            collector_version="0.1.0",
            locator="/test",
            kind="go-deps",
            payload=payload,
        )

        extractor = DependencyMetricsExtractor()
        category = extractor.extract([ev])

        assert category.numeric_metrics["dependency_count"].value == 1.0
        assert category.set_metrics["dependency_names"].items == ["direct-dep"]

    def test_aggregates_across_ecosystems(self) -> None:
        from nfr_review.collectors.payloads.deps import DependencyItem, DepsPayload
        from nfr_review.design_change.dependency_coverage_signals import (
            DependencyMetricsExtractor,
        )

        java_payload = DepsPayload(
            dependencies=[
                DependencyItem(
                    name="spring-core",
                    declared_version="6.0",
                    version_constraint="^6.0",
                    source_file="pom.xml",
                )
            ],
            manifest_files_found=["pom.xml"],
            enrichment_errors=[],
        )
        python_payload = DepsPayload(
            dependencies=[
                DependencyItem(
                    name="requests",
                    declared_version="2.31",
                    version_constraint=">=2.31",
                    source_file="requirements.txt",
                )
            ],
            manifest_files_found=["requirements.txt"],
            enrichment_errors=[],
        )

        evidence = [
            Evidence(
                collector_name="java-deps",
                collector_version="0.1.0",
                locator="/test",
                kind="java-deps",
                payload=java_payload,
            ),
            Evidence(
                collector_name="python-deps",
                collector_version="0.1.0",
                locator="/test",
                kind="python-deps",
                payload=python_payload,
            ),
        ]

        extractor = DependencyMetricsExtractor()
        category = extractor.extract(evidence)

        assert category.numeric_metrics["dependency_count"].value == 2.0
        assert sorted(category.set_metrics["dependency_names"].items) == [
            "requests",
            "spring-core",
        ]

    def test_empty_evidence_returns_empty_category(self) -> None:
        from nfr_review.design_change.dependency_coverage_signals import (
            DependencyMetricsExtractor,
        )

        extractor = DependencyMetricsExtractor()
        category = extractor.extract([])

        assert category.category == "dependencies"
        assert category.numeric_metrics == {}
        assert category.set_metrics == {}


class TestCoverageMetricsExtractor:
    """Tests for the CoverageMetricsExtractor."""

    def test_extracts_line_coverage(self) -> None:
        from nfr_review.collectors.payloads.jacoco import (
            JacocoCoverageMetrics,
            JacocoReportPayload,
        )
        from nfr_review.design_change.dependency_coverage_signals import (
            CoverageMetricsExtractor,
        )

        payload = JacocoReportPayload(
            report_path="/target/site/jacoco/jacoco.xml",
            report_name="test-project",
            overall=JacocoCoverageMetrics(
                line_covered=800,
                line_missed=200,
                line_pct=80.0,
                branch_covered=400,
                branch_missed=100,
                branch_pct=80.0,
                instruction_covered=1600,
                instruction_missed=400,
                instruction_pct=80.0,
            ),
            packages=[],
        )
        ev = Evidence(
            collector_name="jacoco",
            collector_version="0.1.0",
            locator="/test",
            kind="jacoco-report",
            payload=payload,
        )

        extractor = CoverageMetricsExtractor()
        category = extractor.extract([ev])

        assert category.category == "coverage"
        assert category.numeric_metrics["test_coverage"].value == pytest.approx(80.0)

    def test_aggregates_multiple_reports(self) -> None:
        from nfr_review.collectors.payloads.jacoco import (
            JacocoCoverageMetrics,
            JacocoReportPayload,
        )
        from nfr_review.design_change.dependency_coverage_signals import (
            CoverageMetricsExtractor,
        )

        def _make_report(covered: int, missed: int) -> Evidence:
            total = covered + missed
            pct = covered / total * 100.0 if total else 0.0
            payload = JacocoReportPayload(
                report_path="/target/jacoco.xml",
                report_name="module",
                overall=JacocoCoverageMetrics(
                    line_covered=covered,
                    line_missed=missed,
                    line_pct=pct,
                    branch_covered=0,
                    branch_missed=0,
                    branch_pct=0.0,
                    instruction_covered=0,
                    instruction_missed=0,
                    instruction_pct=0.0,
                ),
                packages=[],
            )
            return Evidence(
                collector_name="jacoco",
                collector_version="0.1.0",
                locator="/test",
                kind="jacoco-report",
                payload=payload,
            )

        # Module A: 600/200 = 75%, Module B: 400/800 = 33.3%
        # Combined: 1000/2000 = 50%
        evidence = [_make_report(600, 200), _make_report(400, 800)]

        extractor = CoverageMetricsExtractor()
        category = extractor.extract(evidence)

        assert category.numeric_metrics["test_coverage"].value == pytest.approx(50.0)

    def test_empty_evidence_returns_empty_category(self) -> None:
        from nfr_review.design_change.dependency_coverage_signals import (
            CoverageMetricsExtractor,
        )

        extractor = CoverageMetricsExtractor()
        category = extractor.extract([])

        assert category.category == "coverage"
        assert category.numeric_metrics == {}


class TestDependencyCoverageSignalsDiff:
    """S04 demo criterion: diff two baselines where fixture B added 8 new direct
    dependencies and coverage dropped 12% — both signals fire."""

    def test_dependency_count_jump_fires(self) -> None:
        from nfr_review.design_change.diff import apply_thresholds

        prev = _make_baseline(
            metrics={
                "dependencies": _make_category(
                    "dependencies", numeric={"dependency_count": 20.0}
                )
            }
        )
        curr = _make_baseline(
            metrics={
                "dependencies": _make_category(
                    "dependencies", numeric={"dependency_count": 28.0}
                )
            }
        )

        diffs = diff_baselines(prev, curr)
        result = apply_thresholds(diffs, {"dependency_count": 30.0})

        assert "dependencies" in result
        nd = result["dependencies"].numeric_deltas[0]
        assert nd.name == "dependency_count"
        assert nd.pct_change == pytest.approx(40.0)
        assert nd.pct_change > 30.0

    def test_coverage_drop_fires(self) -> None:
        from nfr_review.design_change.diff import apply_thresholds

        prev = _make_baseline(
            metrics={"coverage": _make_category("coverage", numeric={"test_coverage": 80.0})}
        )
        curr = _make_baseline(
            metrics={"coverage": _make_category("coverage", numeric={"test_coverage": 68.0})}
        )

        diffs = diff_baselines(prev, curr)
        result = apply_thresholds(diffs, {"test_coverage": 5.0})

        assert "coverage" in result
        nd = result["coverage"].numeric_deltas[0]
        assert nd.name == "test_coverage"
        assert nd.pct_change == pytest.approx(-15.0)
        assert abs(nd.pct_change) > 5.0

    def test_dependency_names_set_diff(self) -> None:
        prev = _make_baseline(
            metrics={
                "dependencies": _make_category(
                    "dependencies",
                    sets={
                        "dependency_names": [
                            "spring-core",
                            "spring-web",
                            "guava",
                        ]
                    },
                )
            }
        )
        curr = _make_baseline(
            metrics={
                "dependencies": _make_category(
                    "dependencies",
                    sets={
                        "dependency_names": [
                            "spring-core",
                            "spring-web",
                            "guava",
                            "lombok",
                            "jackson-core",
                            "slf4j-api",
                            "spring-data-jpa",
                            "spring-security",
                            "micrometer",
                            "resilience4j",
                            "caffeine",
                        ]
                    },
                )
            }
        )

        diffs = diff_baselines(prev, curr)

        assert "dependencies" in diffs
        sd = diffs["dependencies"].set_deltas[0]
        assert sd.name == "dependency_names"
        assert len(sd.added) == 8
        assert sd.removed == []

    def test_both_signals_fire_together(self) -> None:
        from nfr_review.config import DEFAULT_DESIGN_CHANGE_THRESHOLDS
        from nfr_review.design_change.diff import apply_thresholds

        prev = _make_baseline(
            metrics={
                "dependencies": _make_category(
                    "dependencies", numeric={"dependency_count": 20.0}
                ),
                "coverage": _make_category("coverage", numeric={"test_coverage": 80.0}),
            }
        )
        curr = _make_baseline(
            metrics={
                "dependencies": _make_category(
                    "dependencies", numeric={"dependency_count": 28.0}
                ),
                "coverage": _make_category("coverage", numeric={"test_coverage": 68.0}),
            }
        )

        diffs = diff_baselines(prev, curr)
        result = apply_thresholds(diffs, DEFAULT_DESIGN_CHANGE_THRESHOLDS)

        # dependency_count: 40% > 30% threshold
        assert "dependencies" in result
        dep_names = {nd.name for nd in result["dependencies"].numeric_deltas}
        assert "dependency_count" in dep_names

        # test_coverage: -15% > 5% threshold (absolute)
        assert "coverage" in result
        cov_names = {nd.name for nd in result["coverage"].numeric_deltas}
        assert "test_coverage" in cov_names

    def test_below_threshold_filtered(self) -> None:
        from nfr_review.design_change.diff import apply_thresholds

        prev = _make_baseline(
            metrics={
                "dependencies": _make_category(
                    "dependencies", numeric={"dependency_count": 20.0}
                ),
                "coverage": _make_category("coverage", numeric={"test_coverage": 80.0}),
            }
        )
        curr = _make_baseline(
            metrics={
                "dependencies": _make_category(
                    "dependencies", numeric={"dependency_count": 21.0}
                ),
                "coverage": _make_category("coverage", numeric={"test_coverage": 79.0}),
            }
        )

        diffs = diff_baselines(prev, curr)
        result = apply_thresholds(diffs, {"dependency_count": 30.0, "test_coverage": 5.0})

        assert result == {}


class TestAdrMetricsExtractor:
    """Tests for the AdrMetricsExtractor."""

    def test_extracts_adr_count_and_titles(self) -> None:
        from nfr_review.collectors.payloads.adr import AdrDocumentPayload
        from nfr_review.design_change.adr_signals import AdrMetricsExtractor

        evidence = [
            Evidence(
                collector_name="adr",
                collector_version="0.1.0",
                locator="/test",
                kind="adr-document",
                payload=AdrDocumentPayload(
                    file_path="docs/adr/0001-use-spring-boot.md",
                    title="Use Spring Boot",
                    status="accepted",
                ),
            ),
            Evidence(
                collector_name="adr",
                collector_version="0.1.0",
                locator="/test",
                kind="adr-document",
                payload=AdrDocumentPayload(
                    file_path="docs/adr/0002-use-postgres.md",
                    title="Use PostgreSQL",
                    status="accepted",
                ),
            ),
        ]

        extractor = AdrMetricsExtractor()
        category = extractor.extract(evidence)

        assert category.category == "adrs"
        assert category.numeric_metrics["adr_count"].value == 2.0
        assert sorted(category.set_metrics["adr_titles"].items) == [
            "Use PostgreSQL",
            "Use Spring Boot",
        ]
        assert category.set_metrics["superseded_adrs"].items == []

    def test_detects_superseded_by_status(self) -> None:
        from nfr_review.collectors.payloads.adr import AdrDocumentPayload
        from nfr_review.design_change.adr_signals import AdrMetricsExtractor

        evidence = [
            Evidence(
                collector_name="adr",
                collector_version="0.1.0",
                locator="/test",
                kind="adr-document",
                payload=AdrDocumentPayload(
                    file_path="docs/adr/0001-use-mysql.md",
                    title="Use MySQL",
                    status="superseded",
                ),
            ),
        ]

        extractor = AdrMetricsExtractor()
        category = extractor.extract(evidence)

        assert category.set_metrics["superseded_adrs"].items == ["Use MySQL"]

    def test_detects_superseded_by_field(self) -> None:
        from nfr_review.collectors.payloads.adr import AdrDocumentPayload
        from nfr_review.design_change.adr_signals import AdrMetricsExtractor

        evidence = [
            Evidence(
                collector_name="adr",
                collector_version="0.1.0",
                locator="/test",
                kind="adr-document",
                payload=AdrDocumentPayload(
                    file_path="docs/adr/0003-use-redis.md",
                    title="Use Redis",
                    status="accepted",
                    superseded_by="0005-use-memcached.md",
                ),
            ),
        ]

        extractor = AdrMetricsExtractor()
        category = extractor.extract(evidence)

        assert category.set_metrics["superseded_adrs"].items == ["Use Redis"]

    def test_falls_back_to_file_path_when_no_title(self) -> None:
        from nfr_review.collectors.payloads.adr import AdrDocumentPayload
        from nfr_review.design_change.adr_signals import AdrMetricsExtractor

        evidence = [
            Evidence(
                collector_name="adr",
                collector_version="0.1.0",
                locator="/test",
                kind="adr-document",
                payload=AdrDocumentPayload(
                    file_path="docs/adr/0004-unnamed.md",
                    title=None,
                    status="accepted",
                ),
            ),
        ]

        extractor = AdrMetricsExtractor()
        category = extractor.extract(evidence)

        assert category.numeric_metrics["adr_count"].value == 1.0
        assert category.set_metrics["adr_titles"].items == ["docs/adr/0004-unnamed.md"]

    def test_empty_evidence_returns_empty_category(self) -> None:
        from nfr_review.design_change.adr_signals import AdrMetricsExtractor

        extractor = AdrMetricsExtractor()
        category = extractor.extract([])

        assert category.category == "adrs"
        assert category.numeric_metrics == {}
        assert category.set_metrics == {}

    def test_ignores_non_adr_evidence(self) -> None:
        from nfr_review.design_change.adr_signals import AdrMetricsExtractor

        evidence = [
            Evidence(
                collector_name="java-ast",
                collector_version="0.1.0",
                locator="/test",
                kind="java-ast-file",
            ),
        ]

        extractor = AdrMetricsExtractor()
        category = extractor.extract(evidence)

        assert category.category == "adrs"
        assert category.numeric_metrics == {}
        assert category.set_metrics == {}

    def test_deprecated_status_treated_as_superseded(self) -> None:
        from nfr_review.collectors.payloads.adr import AdrDocumentPayload
        from nfr_review.design_change.adr_signals import AdrMetricsExtractor

        evidence = [
            Evidence(
                collector_name="adr",
                collector_version="0.1.0",
                locator="/test",
                kind="adr-document",
                payload=AdrDocumentPayload(
                    file_path="docs/adr/0005.md",
                    title="Old Pattern",
                    status="Deprecated",
                ),
            ),
        ]

        extractor = AdrMetricsExtractor()
        category = extractor.extract(evidence)

        assert category.set_metrics["superseded_adrs"].items == ["Old Pattern"]


class TestAdrSignalsDiff:
    """S05 demo criterion: diff two baselines where fixture B has 2 new ADRs
    and 1 superseded — signal fires with ADR titles in finding."""

    def test_new_adrs_detected(self) -> None:
        prev = _make_baseline(
            metrics={
                "adrs": _make_category(
                    "adrs",
                    numeric={"adr_count": 3.0},
                    sets={
                        "adr_titles": [
                            "Use Spring Boot",
                            "Use PostgreSQL",
                            "REST over gRPC",
                        ]
                    },
                )
            }
        )
        curr = _make_baseline(
            metrics={
                "adrs": _make_category(
                    "adrs",
                    numeric={"adr_count": 5.0},
                    sets={
                        "adr_titles": [
                            "Use Spring Boot",
                            "Use PostgreSQL",
                            "REST over gRPC",
                            "Event Sourcing for Audit",
                            "Circuit Breaker Pattern",
                        ]
                    },
                )
            }
        )

        diffs = diff_baselines(prev, curr)

        assert "adrs" in diffs
        nd = [d for d in diffs["adrs"].numeric_deltas if d.name == "adr_count"][0]
        assert nd.delta == 2.0

        sd = [d for d in diffs["adrs"].set_deltas if d.name == "adr_titles"][0]
        assert sorted(sd.added) == ["Circuit Breaker Pattern", "Event Sourcing for Audit"]
        assert sd.removed == []

    def test_superseded_adr_detected(self) -> None:
        prev = _make_baseline(
            metrics={
                "adrs": _make_category(
                    "adrs",
                    sets={"superseded_adrs": []},
                )
            }
        )
        curr = _make_baseline(
            metrics={
                "adrs": _make_category(
                    "adrs",
                    sets={"superseded_adrs": ["REST over gRPC"]},
                )
            }
        )

        diffs = diff_baselines(prev, curr)

        assert "adrs" in diffs
        sd = [d for d in diffs["adrs"].set_deltas if d.name == "superseded_adrs"][0]
        assert sd.added == ["REST over gRPC"]

    def test_full_s05_scenario(self) -> None:
        from nfr_review.config import DEFAULT_DESIGN_CHANGE_THRESHOLDS
        from nfr_review.design_change.diff import apply_thresholds

        prev = _make_baseline(
            metrics={
                "adrs": _make_category(
                    "adrs",
                    numeric={"adr_count": 3.0},
                    sets={
                        "adr_titles": [
                            "Use Spring Boot",
                            "Use PostgreSQL",
                            "REST over gRPC",
                        ],
                        "superseded_adrs": [],
                    },
                )
            }
        )
        curr = _make_baseline(
            metrics={
                "adrs": _make_category(
                    "adrs",
                    numeric={"adr_count": 5.0},
                    sets={
                        "adr_titles": [
                            "Use Spring Boot",
                            "Use PostgreSQL",
                            "REST over gRPC",
                            "Event Sourcing for Audit",
                            "Circuit Breaker Pattern",
                        ],
                        "superseded_adrs": ["REST over gRPC"],
                    },
                )
            }
        )

        diffs = diff_baselines(prev, curr)
        result = apply_thresholds(diffs, DEFAULT_DESIGN_CHANGE_THRESHOLDS)

        # adr_count: 3 -> 5 = +66.7%, threshold is 1.0 (set threshold = min items)
        assert "adrs" in result

        # New ADR titles visible
        title_deltas = [d for d in result["adrs"].set_deltas if d.name == "adr_titles"]
        assert len(title_deltas) == 1
        assert sorted(title_deltas[0].added) == [
            "Circuit Breaker Pattern",
            "Event Sourcing for Audit",
        ]

        # Superseded ADR visible
        superseded_deltas = [
            d for d in result["adrs"].set_deltas if d.name == "superseded_adrs"
        ]
        assert len(superseded_deltas) == 1
        assert superseded_deltas[0].added == ["REST over gRPC"]

    def test_below_threshold_filtered(self) -> None:
        from nfr_review.design_change.diff import apply_thresholds

        prev = _make_baseline(
            metrics={"adrs": _make_category("adrs", numeric={"adr_count": 10.0})}
        )
        curr = _make_baseline(
            metrics={"adrs": _make_category("adrs", numeric={"adr_count": 10.0})}
        )

        diffs = diff_baselines(prev, curr)
        result = apply_thresholds(diffs, {"adr_count": 1.0})

        assert "adrs" not in result


class TestApiSurfaceExtractor:
    """Tests for the ApiSurfaceExtractor."""

    def test_extracts_proto_rpcs(self) -> None:
        from nfr_review.collectors.payloads.proto import (
            ProtoAnalysisPayload,
            ProtoRpcMethod,
            ProtoService,
        )
        from nfr_review.design_change.api_surface_signals import ApiSurfaceExtractor

        payload = ProtoAnalysisPayload(
            file_path="api/order.proto",
            syntax="proto3",
            package="com.example.order",
            imports=[],
            messages=[],
            services=[
                ProtoService(
                    name="OrderService",
                    line=10,
                    has_comment=True,
                    methods=[
                        ProtoRpcMethod(
                            name="CreateOrder",
                            request_type="CreateOrderRequest",
                            response_type="CreateOrderResponse",
                            line=12,
                            has_comment=True,
                        ),
                        ProtoRpcMethod(
                            name="GetOrder",
                            request_type="GetOrderRequest",
                            response_type="GetOrderResponse",
                            line=14,
                            has_comment=True,
                        ),
                    ],
                ),
            ],
            enums=[],
        )

        ev = Evidence(
            collector_name="proto",
            collector_version="0.1.0",
            locator="/test",
            kind="proto-analysis",
            payload=payload,
        )

        extractor = ApiSurfaceExtractor()
        category = extractor.extract([ev])

        assert category.category == "api_surface"
        assert category.numeric_metrics["api_endpoint_count"].value == 2.0
        assert sorted(category.set_metrics["api_endpoints"].items) == [
            "OrderService.CreateOrder",
            "OrderService.GetOrder",
        ]

    def test_extracts_openapi_endpoints(self) -> None:
        from nfr_review.collectors.payloads.openapi import (
            OpenApiAnalysisPayload,
            OpenApiEndpoint,
        )
        from nfr_review.design_change.api_surface_signals import ApiSurfaceExtractor

        payload = OpenApiAnalysisPayload(
            file_path="api/openapi.yaml",
            openapi_version="3.0.1",
            title="Order API",
            endpoints=[
                OpenApiEndpoint(method="GET", path="/api/orders"),
                OpenApiEndpoint(method="POST", path="/api/orders"),
                OpenApiEndpoint(method="DELETE", path="/api/orders/{id}"),
            ],
        )

        ev = Evidence(
            collector_name="openapi",
            collector_version="0.1.0",
            locator="/test",
            kind="openapi-analysis",
            payload=payload,
        )

        extractor = ApiSurfaceExtractor()
        category = extractor.extract([ev])

        assert category.category == "api_surface"
        assert category.numeric_metrics["api_endpoint_count"].value == 3.0
        assert sorted(category.set_metrics["api_endpoints"].items) == [
            "DELETE /api/orders/{id}",
            "GET /api/orders",
            "POST /api/orders",
        ]

    def test_combines_proto_and_openapi(self) -> None:
        from nfr_review.collectors.payloads.openapi import (
            OpenApiAnalysisPayload,
            OpenApiEndpoint,
        )
        from nfr_review.collectors.payloads.proto import (
            ProtoAnalysisPayload,
            ProtoRpcMethod,
            ProtoService,
        )
        from nfr_review.design_change.api_surface_signals import ApiSurfaceExtractor

        proto_ev = Evidence(
            collector_name="proto",
            collector_version="0.1.0",
            locator="/test",
            kind="proto-analysis",
            payload=ProtoAnalysisPayload(
                file_path="api/order.proto",
                imports=[],
                messages=[],
                services=[
                    ProtoService(
                        name="OrderService",
                        line=1,
                        has_comment=True,
                        methods=[
                            ProtoRpcMethod(
                                name="CreateOrder",
                                request_type="Req",
                                response_type="Resp",
                                line=2,
                                has_comment=True,
                            ),
                        ],
                    ),
                ],
                enums=[],
            ),
        )
        openapi_ev = Evidence(
            collector_name="openapi",
            collector_version="0.1.0",
            locator="/test",
            kind="openapi-analysis",
            payload=OpenApiAnalysisPayload(
                file_path="api/openapi.yaml",
                endpoints=[
                    OpenApiEndpoint(method="GET", path="/api/orders"),
                ],
            ),
        )

        extractor = ApiSurfaceExtractor()
        category = extractor.extract([proto_ev, openapi_ev])

        assert category.numeric_metrics["api_endpoint_count"].value == 2.0
        assert sorted(category.set_metrics["api_endpoints"].items) == [
            "GET /api/orders",
            "OrderService.CreateOrder",
        ]

    def test_normalises_http_method_to_uppercase(self) -> None:
        from nfr_review.collectors.payloads.openapi import (
            OpenApiAnalysisPayload,
            OpenApiEndpoint,
        )
        from nfr_review.design_change.api_surface_signals import ApiSurfaceExtractor

        payload = OpenApiAnalysisPayload(
            file_path="api/spec.yaml",
            endpoints=[OpenApiEndpoint(method="get", path="/health")],
        )
        ev = Evidence(
            collector_name="openapi",
            collector_version="0.1.0",
            locator="/test",
            kind="openapi-analysis",
            payload=payload,
        )

        extractor = ApiSurfaceExtractor()
        category = extractor.extract([ev])

        assert category.set_metrics["api_endpoints"].items == ["GET /health"]

    def test_multiple_proto_services(self) -> None:
        from nfr_review.collectors.payloads.proto import (
            ProtoAnalysisPayload,
            ProtoRpcMethod,
            ProtoService,
        )
        from nfr_review.design_change.api_surface_signals import ApiSurfaceExtractor

        payload = ProtoAnalysisPayload(
            file_path="api/services.proto",
            imports=[],
            messages=[],
            services=[
                ProtoService(
                    name="UserService",
                    line=1,
                    has_comment=True,
                    methods=[
                        ProtoRpcMethod(
                            name="GetUser",
                            request_type="Req",
                            response_type="Resp",
                            line=2,
                            has_comment=True,
                        ),
                    ],
                ),
                ProtoService(
                    name="AuthService",
                    line=10,
                    has_comment=True,
                    methods=[
                        ProtoRpcMethod(
                            name="Login",
                            request_type="Req",
                            response_type="Resp",
                            line=11,
                            has_comment=True,
                        ),
                        ProtoRpcMethod(
                            name="Logout",
                            request_type="Req",
                            response_type="Resp",
                            line=12,
                            has_comment=True,
                        ),
                    ],
                ),
            ],
            enums=[],
        )

        ev = Evidence(
            collector_name="proto",
            collector_version="0.1.0",
            locator="/test",
            kind="proto-analysis",
            payload=payload,
        )

        extractor = ApiSurfaceExtractor()
        category = extractor.extract([ev])

        assert category.numeric_metrics["api_endpoint_count"].value == 3.0
        assert sorted(category.set_metrics["api_endpoints"].items) == [
            "AuthService.Login",
            "AuthService.Logout",
            "UserService.GetUser",
        ]

    def test_empty_evidence_returns_empty_category(self) -> None:
        from nfr_review.design_change.api_surface_signals import ApiSurfaceExtractor

        extractor = ApiSurfaceExtractor()
        category = extractor.extract([])

        assert category.category == "api_surface"
        assert category.numeric_metrics == {}
        assert category.set_metrics == {}

    def test_ignores_non_api_evidence(self) -> None:
        from nfr_review.design_change.api_surface_signals import ApiSurfaceExtractor

        evidence = [
            Evidence(
                collector_name="java-ast",
                collector_version="0.1.0",
                locator="/test",
                kind="java-ast-file",
            ),
        ]

        extractor = ApiSurfaceExtractor()
        category = extractor.extract(evidence)

        assert category.category == "api_surface"
        assert category.numeric_metrics == {}
        assert category.set_metrics == {}

    def test_deduplicates_across_files(self) -> None:
        from nfr_review.collectors.payloads.proto import (
            ProtoAnalysisPayload,
            ProtoRpcMethod,
            ProtoService,
        )
        from nfr_review.design_change.api_surface_signals import ApiSurfaceExtractor

        svc = ProtoService(
            name="OrderService",
            line=1,
            has_comment=True,
            methods=[
                ProtoRpcMethod(
                    name="CreateOrder",
                    request_type="Req",
                    response_type="Resp",
                    line=2,
                    has_comment=True,
                ),
            ],
        )

        evidence = [
            Evidence(
                collector_name="proto",
                collector_version="0.1.0",
                locator="/test",
                kind="proto-analysis",
                payload=ProtoAnalysisPayload(
                    file_path="api/v1/order.proto",
                    imports=[],
                    messages=[],
                    services=[svc],
                    enums=[],
                ),
            ),
            Evidence(
                collector_name="proto",
                collector_version="0.1.0",
                locator="/test",
                kind="proto-analysis",
                payload=ProtoAnalysisPayload(
                    file_path="api/v1/order_copy.proto",
                    imports=[],
                    messages=[],
                    services=[svc],
                    enums=[],
                ),
            ),
        ]

        extractor = ApiSurfaceExtractor()
        category = extractor.extract(evidence)

        assert category.numeric_metrics["api_endpoint_count"].value == 1.0
        assert category.set_metrics["api_endpoints"].items == ["OrderService.CreateOrder"]


class TestApiSurfaceSignalsDiff:
    """S06 demo criterion: diff two baselines where fixture B added 3 new proto RPCs,
    2 new OpenAPI endpoints, and removed 1 endpoint — finding shows specific
    additions and removals."""

    def test_new_proto_rpcs_detected(self) -> None:
        prev = _make_baseline(
            metrics={
                "api_surface": _make_category(
                    "api_surface",
                    numeric={"api_endpoint_count": 2.0},
                    sets={
                        "api_endpoints": [
                            "OrderService.CreateOrder",
                            "OrderService.GetOrder",
                        ]
                    },
                )
            }
        )
        curr = _make_baseline(
            metrics={
                "api_surface": _make_category(
                    "api_surface",
                    numeric={"api_endpoint_count": 5.0},
                    sets={
                        "api_endpoints": [
                            "OrderService.CreateOrder",
                            "OrderService.GetOrder",
                            "OrderService.UpdateOrder",
                            "OrderService.DeleteOrder",
                            "OrderService.ListOrders",
                        ]
                    },
                )
            }
        )

        diffs = diff_baselines(prev, curr)

        assert "api_surface" in diffs
        nd = [
            d for d in diffs["api_surface"].numeric_deltas if d.name == "api_endpoint_count"
        ][0]
        assert nd.delta == 3.0

        sd = [d for d in diffs["api_surface"].set_deltas if d.name == "api_endpoints"][0]
        assert sorted(sd.added) == [
            "OrderService.DeleteOrder",
            "OrderService.ListOrders",
            "OrderService.UpdateOrder",
        ]
        assert sd.removed == []

    def test_removed_endpoint_detected(self) -> None:
        prev = _make_baseline(
            metrics={
                "api_surface": _make_category(
                    "api_surface",
                    sets={
                        "api_endpoints": [
                            "GET /api/orders",
                            "POST /api/orders",
                            "DELETE /api/orders/{id}",
                        ]
                    },
                )
            }
        )
        curr = _make_baseline(
            metrics={
                "api_surface": _make_category(
                    "api_surface",
                    sets={
                        "api_endpoints": [
                            "GET /api/orders",
                            "POST /api/orders",
                        ]
                    },
                )
            }
        )

        diffs = diff_baselines(prev, curr)

        assert "api_surface" in diffs
        sd = [d for d in diffs["api_surface"].set_deltas if d.name == "api_endpoints"][0]
        assert sd.removed == ["DELETE /api/orders/{id}"]
        assert sd.added == []

    def test_full_s06_scenario(self) -> None:
        """Fixture B added 3 new proto RPCs, 2 new OpenAPI endpoints,
        and removed 1 endpoint."""
        from nfr_review.config import DEFAULT_DESIGN_CHANGE_THRESHOLDS
        from nfr_review.design_change.diff import apply_thresholds

        prev = _make_baseline(
            metrics={
                "api_surface": _make_category(
                    "api_surface",
                    numeric={"api_endpoint_count": 5.0},
                    sets={
                        "api_endpoints": [
                            "OrderService.CreateOrder",
                            "OrderService.GetOrder",
                            "GET /api/orders",
                            "POST /api/orders",
                            "DELETE /api/orders/{id}",
                        ]
                    },
                )
            }
        )
        curr = _make_baseline(
            metrics={
                "api_surface": _make_category(
                    "api_surface",
                    numeric={"api_endpoint_count": 9.0},
                    sets={
                        "api_endpoints": [
                            "OrderService.CreateOrder",
                            "OrderService.GetOrder",
                            "OrderService.UpdateOrder",
                            "OrderService.DeleteOrder",
                            "OrderService.ListOrders",
                            "GET /api/orders",
                            "POST /api/orders",
                            "GET /api/orders/{id}/status",
                            "PUT /api/orders/{id}",
                        ]
                    },
                )
            }
        )

        diffs = diff_baselines(prev, curr)
        result = apply_thresholds(diffs, DEFAULT_DESIGN_CHANGE_THRESHOLDS)

        assert "api_surface" in result

        # Count delta: 5 -> 9
        nd = [
            d for d in result["api_surface"].numeric_deltas if d.name == "api_endpoint_count"
        ]
        assert len(nd) == 1
        assert nd[0].delta == 4.0

        # Set delta: 3 proto RPCs added + 2 OpenAPI endpoints added, 1 removed
        sd = [d for d in result["api_surface"].set_deltas if d.name == "api_endpoints"]
        assert len(sd) == 1
        assert sorted(sd[0].added) == [
            "GET /api/orders/{id}/status",
            "OrderService.DeleteOrder",
            "OrderService.ListOrders",
            "OrderService.UpdateOrder",
            "PUT /api/orders/{id}",
        ]
        assert sd[0].removed == ["DELETE /api/orders/{id}"]

    def test_below_threshold_filtered(self) -> None:
        from nfr_review.design_change.diff import apply_thresholds

        prev = _make_baseline(
            metrics={
                "api_surface": _make_category(
                    "api_surface", numeric={"api_endpoint_count": 10.0}
                )
            }
        )
        curr = _make_baseline(
            metrics={
                "api_surface": _make_category(
                    "api_surface", numeric={"api_endpoint_count": 10.0}
                )
            }
        )

        diffs = diff_baselines(prev, curr)
        result = apply_thresholds(diffs, {"api_endpoint_count": 1.0})

        assert "api_surface" not in result
