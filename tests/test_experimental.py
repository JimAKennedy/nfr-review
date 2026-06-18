# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for the experimental class-diagram-focused report feature."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from pydantic import ValidationError

from nfr_review.arch_models import C4Diagram
from nfr_review.cli import cli
from nfr_review.experimental_models import (
    CrossRepoEdge,
    DynamicAnalysisSection,
    ExperimentalReport,
)
from nfr_review.experimental_orchestrator import run_experimental_review
from nfr_review.output.experimental_render import render_experimental_report

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CPP_FIXTURE = Path(__file__).parent / "fixtures" / "cpp-integration-repo"


@pytest.fixture()
def sample_diagrams() -> list[C4Diagram]:
    return [
        C4Diagram(
            level="code",
            title="Class Diagram 1",
            scope="classes",
            mermaid="classDiagram\n    class Widget {\n        +name() string\n    }\n",
            component_ids=[],
        ),
    ]


@pytest.fixture()
def sample_edges() -> list[CrossRepoEdge]:
    return [
        CrossRepoEdge(
            source_repo="repo-a",
            target_repo="repo-b",
            source_class="PluginProcessor",
            target_class="AudioProcessor",
        ),
    ]


@pytest.fixture()
def sample_report(
    sample_diagrams: list[C4Diagram],
    sample_edges: list[CrossRepoEdge],
) -> ExperimentalReport:
    return ExperimentalReport(
        repo_name="test-repo",
        class_diagrams=sample_diagrams,
        cross_repo_edges=sample_edges,
        metadata={
            "timestamp": "2026-06-17T00:00:00Z",
            "version": "0.1.0",
            "repos_analyzed": 1,
        },
    )


# ===================================================================
# 1. ExperimentalReport model tests
# ===================================================================


class TestExperimentalReportModel:
    def test_construction_with_all_fields(
        self,
        sample_diagrams: list[C4Diagram],
        sample_edges: list[CrossRepoEdge],
    ) -> None:
        report = ExperimentalReport(
            repo_name="my-repo",
            class_diagrams=sample_diagrams,
            cross_repo_edges=sample_edges,
            metadata={"timestamp": "2026-01-01T00:00:00Z"},
        )
        assert report.repo_name == "my-repo"
        assert len(report.class_diagrams) == 1
        assert len(report.cross_repo_edges) == 1
        assert report.metadata["timestamp"] == "2026-01-01T00:00:00Z"

    def test_empty_defaults(self) -> None:
        report = ExperimentalReport(repo_name="empty-repo")
        assert report.repo_name == "empty-repo"
        assert report.class_diagrams == []
        assert report.cross_repo_edges == []
        assert report.metadata == {}

    def test_cross_repo_edge_validation(self) -> None:
        edge = CrossRepoEdge(
            source_repo="alpha",
            target_repo="beta",
            source_class="Foo",
            target_class="Bar",
        )
        assert edge.source_repo == "alpha"
        assert edge.target_repo == "beta"
        assert edge.source_class == "Foo"
        assert edge.target_class == "Bar"

    def test_cross_repo_edge_forbids_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            CrossRepoEdge(
                source_repo="a",
                target_repo="b",
                source_class="C",
                target_class="D",
                unknown_field="x",  # type: ignore[call-arg]
            )

    def test_experimental_report_forbids_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            ExperimentalReport(
                repo_name="test",
                bogus="nope",  # type: ignore[call-arg]
            )

    def test_model_dump_roundtrip(self, sample_report: ExperimentalReport) -> None:
        data = sample_report.model_dump()
        restored = ExperimentalReport.model_validate(data)
        assert restored == sample_report


# ===================================================================
# 2. run_experimental_review() tests
# ===================================================================


class TestRunExperimentalReview:
    def test_with_cpp_fixture(self) -> None:
        """The cpp-integration-repo has C++ classes, should produce diagrams."""
        assert CPP_FIXTURE.exists(), f"Fixture missing: {CPP_FIXTURE}"
        report = run_experimental_review([CPP_FIXTURE])
        assert isinstance(report, ExperimentalReport)
        assert report.repo_name == "cpp-integration-repo"
        assert report.metadata.get("version") is not None
        assert report.metadata.get("timestamp") is not None
        # The fixture has Widget, FancyWidget, LegacyData -- at least some classes
        # Class diagrams may or may not be produced depending on collector availability
        # but the report should be valid either way.

    def test_with_no_classes_fixture(self, tmp_path: Path) -> None:
        """A directory with no source code should produce empty class_diagrams."""
        empty_repo = tmp_path / "empty-repo"
        empty_repo.mkdir()
        # Create a minimal file so the directory is not completely empty
        (empty_repo / "README.md").write_text("# Empty\n")

        report = run_experimental_review([empty_repo])
        assert isinstance(report, ExperimentalReport)
        assert report.repo_name == "empty-repo"
        assert report.class_diagrams == []
        assert report.cross_repo_edges == []

    def test_progress_callback_is_called(self) -> None:
        """Progress callback should be invoked with (phase, detail) pairs."""
        calls: list[tuple[str, str]] = []

        def tracker(phase: str, detail: str) -> None:
            calls.append((phase, detail))

        empty_repo = Path(__file__).parent
        report = run_experimental_review([empty_repo], progress_callback=tracker)
        assert isinstance(report, ExperimentalReport)
        # At minimum, the "collecting" phase should fire
        phases_seen = {c[0] for c in calls}
        assert "collecting" in phases_seen

    def test_multiple_targets(self, tmp_path: Path) -> None:
        """Multiple targets should be accepted."""
        repo_a = tmp_path / "repo-a"
        repo_b = tmp_path / "repo-b"
        repo_a.mkdir()
        repo_b.mkdir()
        (repo_a / "README.md").write_text("# A\n")
        (repo_b / "README.md").write_text("# B\n")

        report = run_experimental_review([repo_a, repo_b])
        assert report.repo_name == "repo-a"
        assert report.metadata["repos_analyzed"] == 2


# ===================================================================
# 3. render_experimental_report() tests
# ===================================================================


class TestRenderExperimentalReport:
    def test_json_output_contains_expected_keys(
        self, tmp_path: Path, sample_report: ExperimentalReport
    ) -> None:
        results = render_experimental_report(sample_report, tmp_path, formats=["json"])
        assert results["json"] is not None
        json_path = results["json"]
        assert json_path.exists()

        data = json.loads(json_path.read_text())
        assert "repo_name" in data
        assert "class_diagrams" in data
        assert "cross_repo_edges" in data
        assert "metadata" in data
        assert data["repo_name"] == "test-repo"

    def test_json_roundtrip(self, tmp_path: Path, sample_report: ExperimentalReport) -> None:
        results = render_experimental_report(sample_report, tmp_path, formats=["json"])
        json_path = results["json"]
        data = json.loads(json_path.read_text())
        restored = ExperimentalReport.model_validate(data)
        assert restored == sample_report

    def test_markdown_has_class_diagram_mermaid_blocks(
        self, tmp_path: Path, sample_report: ExperimentalReport
    ) -> None:
        results = render_experimental_report(sample_report, tmp_path, formats=["md"])
        assert results["md"] is not None
        content = results["md"].read_text()

        assert "# Experimental Report" in content
        assert "```mermaid" in content
        assert "classDiagram" in content
        assert "Widget" in content

    def test_markdown_cross_repo_edge_table(
        self, tmp_path: Path, sample_report: ExperimentalReport
    ) -> None:
        results = render_experimental_report(sample_report, tmp_path, formats=["md"])
        content = results["md"].read_text()

        assert "## Cross-Repository Edges" in content
        assert "repo-a" in content
        assert "repo-b" in content
        assert "PluginProcessor" in content
        assert "AudioProcessor" in content
        # Table header
        assert "| Source Repo |" in content

    def test_markdown_no_diagrams(self, tmp_path: Path) -> None:
        report = ExperimentalReport(repo_name="empty")
        results = render_experimental_report(report, tmp_path, formats=["md"])
        content = results["md"].read_text()
        assert "No class diagrams generated." in content
        assert "No cross-repository edges detected." in content

    def test_markdown_no_cross_repo_edges(
        self, tmp_path: Path, sample_diagrams: list[C4Diagram]
    ) -> None:
        report = ExperimentalReport(
            repo_name="single-repo",
            class_diagrams=sample_diagrams,
        )
        results = render_experimental_report(report, tmp_path, formats=["md"])
        content = results["md"].read_text()
        assert "No cross-repository edges detected." in content
        assert "```mermaid" in content

    def test_both_formats_produced(
        self, tmp_path: Path, sample_report: ExperimentalReport
    ) -> None:
        results = render_experimental_report(sample_report, tmp_path)
        assert "json" in results
        assert "md" in results
        assert results["json"] is not None
        assert results["md"] is not None
        assert results["json"].exists()
        assert results["md"].exists()

    def test_unknown_format_returns_none(
        self, tmp_path: Path, sample_report: ExperimentalReport
    ) -> None:
        results = render_experimental_report(sample_report, tmp_path, formats=["xml"])
        assert results["xml"] is None

    def test_creates_output_directory(
        self, tmp_path: Path, sample_report: ExperimentalReport
    ) -> None:
        out_dir = tmp_path / "nested" / "output"
        results = render_experimental_report(sample_report, out_dir)
        assert out_dir.exists()
        assert results["json"].exists()

    def test_metadata_in_markdown(
        self, tmp_path: Path, sample_report: ExperimentalReport
    ) -> None:
        results = render_experimental_report(sample_report, tmp_path, formats=["md"])
        content = results["md"].read_text()
        assert "test-repo" in content
        assert "2026-06-17T00:00:00Z" in content
        assert "0.1.0" in content


# ===================================================================
# 4. CLI command tests
# ===================================================================


class TestExperimentalCli:
    def test_help_shows_deprecated(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["experimental", "--help"])
        assert result.exit_code == 0
        assert "DEPRECATED" in result.output or "deprecated" in result.output.lower()
        assert "TARGET" in result.output or "targets" in result.output.lower()

    def test_basic_invocation_delegates_to_arch(self, tmp_path: Path) -> None:
        """Deprecated experimental command delegates to arch."""
        runner = CliRunner()
        output_dir = tmp_path / "reports"
        result = runner.invoke(
            cli,
            [
                "experimental",
                str(CPP_FIXTURE),
                "--output-dir",
                str(output_dir),
                "--format",
                "json",
                "-q",
            ],
        )
        assert result.exit_code == 0, (
            f"CLI failed with exit_code={result.exit_code}\noutput={result.output}\n"
        )
        json_files = list(output_dir.glob("*.json"))
        assert len(json_files) >= 1

    def test_missing_target_fails(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["experimental"])
        assert result.exit_code != 0

    def test_verbose_and_quiet_mutually_exclusive(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["experimental", str(CPP_FIXTURE), "-v", "-q"],
        )
        assert result.exit_code != 0


# ===================================================================
# 5. Dynamic analysis integration tests
# ===================================================================


def _make_trace_evidence() -> list:
    """Create fake OTel trace evidence for testing."""
    from nfr_review.models import Evidence

    return [
        Evidence(
            collector_name="otel-trace",
            collector_version="1.0.0",
            locator="traces.jsonl",
            kind="otel-trace",
            payload={
                "spans": [
                    {
                        "trace_id": "abc123",
                        "span_id": "span-1",
                        "parent_span_id": "",
                        "name": "GET /api/orders",
                        "service_name": "order-service",
                        "kind": 2,
                        "start_time_unix_nano": 1000000000,
                        "end_time_unix_nano": 2000000000,
                        "status_code": 1,
                        "code_namespace": "com.example",
                        "code_function": "getOrders",
                        "attributes": {},
                    },
                    {
                        "trace_id": "abc123",
                        "span_id": "span-2",
                        "parent_span_id": "span-1",
                        "name": "POST /api/payments",
                        "service_name": "payment-service",
                        "kind": 3,
                        "start_time_unix_nano": 1100000000,
                        "end_time_unix_nano": 1900000000,
                        "status_code": 1,
                        "code_namespace": "com.example",
                        "code_function": "processPayment",
                        "attributes": {},
                    },
                ],
                "trace_ids": ["abc123"],
                "service_names": ["order-service", "payment-service"],
                "source_file": "traces.jsonl",
            },
        ),
    ]


class TestDynamicAnalysisModel:
    def test_section_defaults(self) -> None:
        section = DynamicAnalysisSection()
        assert section.service_count == 0
        assert section.edge_count == 0
        assert section.topology_mermaid == ""
        assert section.services == []

    def test_section_with_data(self) -> None:
        section = DynamicAnalysisSection(
            service_count=2,
            edge_count=1,
            topology_mermaid="graph TD\n  A --> B\n",
            services=["order-service", "payment-service"],
        )
        assert section.service_count == 2
        assert "graph TD" in section.topology_mermaid

    def test_report_with_dynamic_analysis(self) -> None:
        section = DynamicAnalysisSection(
            service_count=2,
            edge_count=1,
            topology_mermaid="graph TD\n  A --> B\n",
            services=["svc-a", "svc-b"],
        )
        report = ExperimentalReport(
            repo_name="test",
            dynamic_analysis=section,
        )
        assert report.dynamic_analysis is not None
        assert report.dynamic_analysis.service_count == 2

    def test_report_without_dynamic_analysis(self) -> None:
        report = ExperimentalReport(repo_name="test")
        assert report.dynamic_analysis is None


class TestDynamicAnalysisOrchestrator:
    def test_with_otel_evidence(self) -> None:
        evidence = _make_trace_evidence()
        report = run_experimental_review(
            [CPP_FIXTURE],
            evidence=evidence,
        )
        assert report.dynamic_analysis is not None
        assert report.dynamic_analysis.service_count == 2
        assert "order-service" in report.dynamic_analysis.services
        assert "payment-service" in report.dynamic_analysis.services
        assert report.dynamic_analysis.edge_count >= 1
        assert "graph TD" in report.dynamic_analysis.topology_mermaid

    def test_without_evidence(self) -> None:
        report = run_experimental_review([CPP_FIXTURE])
        assert report.dynamic_analysis is None

    def test_with_empty_evidence(self) -> None:
        report = run_experimental_review([CPP_FIXTURE], evidence=[])
        assert report.dynamic_analysis is None

    def test_with_non_trace_evidence(self) -> None:
        from nfr_review.models import Evidence

        evidence = [
            Evidence(
                collector_name="repo",
                collector_version="1.0.0",
                locator=".",
                kind="repo-analysis",
                payload={"has_readme": True},
            ),
        ]
        report = run_experimental_review([CPP_FIXTURE], evidence=evidence)
        assert report.dynamic_analysis is None


class TestDynamicAnalysisRenderer:
    def test_markdown_includes_dynamic_section(self, tmp_path: Path) -> None:
        section = DynamicAnalysisSection(
            service_count=2,
            edge_count=1,
            topology_mermaid="graph TD\n  order_service --> payment_service\n",
            services=["order-service", "payment-service"],
        )
        report = ExperimentalReport(
            repo_name="test-repo",
            dynamic_analysis=section,
            metadata={"timestamp": "2026-06-17T00:00:00Z"},
        )
        results = render_experimental_report(report, tmp_path, formats=["md"])
        md_path = results["md"]
        assert md_path is not None
        content = md_path.read_text()
        assert "## Dynamic Analysis" in content
        assert "order-service" in content
        assert "payment-service" in content
        assert "```mermaid" in content
        assert "graph TD" in content
        assert "Services observed:** 2" in content
        assert "Cross-service edges:** 1" in content

    def test_markdown_omits_dynamic_when_absent(self, tmp_path: Path) -> None:
        report = ExperimentalReport(
            repo_name="test-repo",
            metadata={"timestamp": "2026-06-17T00:00:00Z"},
        )
        results = render_experimental_report(report, tmp_path, formats=["md"])
        content = results["md"].read_text()
        assert "## Dynamic Analysis" not in content

    def test_json_includes_dynamic_section(self, tmp_path: Path) -> None:
        section = DynamicAnalysisSection(
            service_count=3,
            edge_count=2,
            topology_mermaid="graph TD\n",
            services=["a", "b", "c"],
        )
        report = ExperimentalReport(
            repo_name="test-repo",
            dynamic_analysis=section,
        )
        results = render_experimental_report(report, tmp_path, formats=["json"])
        data = json.loads(results["json"].read_text())
        assert data["dynamic_analysis"]["service_count"] == 3
        assert data["dynamic_analysis"]["services"] == ["a", "b", "c"]

    def test_json_null_dynamic_when_absent(self, tmp_path: Path) -> None:
        report = ExperimentalReport(repo_name="test-repo")
        results = render_experimental_report(report, tmp_path, formats=["json"])
        data = json.loads(results["json"].read_text())
        assert data["dynamic_analysis"] is None


class TestEvidenceDirCli:
    def test_evidence_dir_option_loads_traces(self, tmp_path: Path) -> None:
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()

        trace_data = {
            "collector_name": "otel-trace",
            "collector_version": "1.0.0",
            "locator": "traces.jsonl",
            "kind": "otel-trace",
            "payload": {
                "spans": [
                    {
                        "trace_id": "t1",
                        "span_id": "s1",
                        "parent_span_id": "",
                        "name": "GET /",
                        "service_name": "web",
                        "kind": 2,
                        "start_time_unix_nano": 1000000000,
                        "end_time_unix_nano": 2000000000,
                        "status_code": 1,
                        "code_namespace": "",
                        "code_function": "",
                        "attributes": {},
                    },
                ],
                "trace_ids": ["t1"],
                "service_names": ["web"],
                "source_file": "traces.jsonl",
            },
        }
        (evidence_dir / "traces.jsonl").write_text(json.dumps(trace_data) + "\n")

        runner = CliRunner()
        out_dir = tmp_path / "out"
        result = runner.invoke(
            cli,
            [
                "experimental",
                str(CPP_FIXTURE),
                "--evidence-dir",
                str(evidence_dir),
                "--output-dir",
                str(out_dir),
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0, result.output + (
            result.stderr if hasattr(result, "stderr") else ""
        )
        # Deprecated experimental delegates to arch, which writes *-architecture-report.json
        json_files = list(out_dir.glob("*-architecture-report.json"))
        assert len(json_files) >= 1, (
            f"Expected arch JSON report in {out_dir}: {list(out_dir.iterdir())}"
        )
        data = json.loads(json_files[0].read_text())
        assert data.get("dynamic_analysis") is not None
        assert data["dynamic_analysis"]["service_count"] >= 1
