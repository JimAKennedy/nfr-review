# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for multi-format architecture report rendering."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nfr_review.arch_models import (
    ArchReport,
    ArchReportMetadata,
    BoundedContext,
    C4Diagram,
    Component,
    ComponentBoundary,
    ComponentTestCoverage,
    DomainEntity,
    DomainModelSection,
    DynamicScenario,
    EntityRelationship,
    IntegrationPoint,
    MarketAnalysisSection,
    MarketComparison,
    Recommendation,
    RepoInfo,
    RiskFinding,
    ScenarioStep,
    TechStackEntry,
)
from nfr_review.arch_report_render import (
    render_arch_json,
    render_arch_markdown,
    render_arch_pdf,
    render_arch_report,
)

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _make_metadata() -> ArchReportMetadata:
    return ArchReportMetadata(
        tool_version="0.1.0",
        timestamp="2026-05-25T12:00:00Z",
        repos_analyzed=[
            RepoInfo(
                path="/tmp/repo",
                name="test-repo",
                git_sha="abc1234",
                git_branch="main",
            )
        ],
        llm_available=True,
        llm_model="claude-sonnet-4-6",
    )


def _make_full_report() -> ArchReport:
    """Construct a fully-populated ArchReport for rendering tests."""
    return ArchReport(
        metadata=_make_metadata(),
        components=[
            Component(
                id="comp-api",
                name="API Service",
                description="REST API gateway",
                component_type="service",
                boundaries=[ComponentBoundary(boundary_type="directory", path="src/api")],
                responsibilities=["Handle HTTP requests", "Route to services"],
                tech_stack=[TechStackEntry(name="FastAPI", version="0.100", role="framework")],
                repo="test-repo",
            ),
            Component(
                id="comp-db",
                name="Database",
                description="PostgreSQL data store",
                component_type="database",
                boundaries=[],
                responsibilities=["Persist domain data"],
                tech_stack=[TechStackEntry(name="PostgreSQL", version="15")],
            ),
        ],
        integration_points=[
            IntegrationPoint(
                id="int-01",
                source_component_id="comp-api",
                target_component_id="comp-db",
                style="synchronous",
                protocol="SQL",
                description="API queries database",
                data_flow="request/response",
            )
        ],
        dynamic_scenarios=[
            DynamicScenario(
                id="scenario-01",
                name="User Login",
                description="User authenticates via API",
                trigger="POST /login",
                steps=[
                    ScenarioStep(
                        sequence=1,
                        from_component_id="comp-api",
                        to_component_id="comp-db",
                        action="SELECT user credentials",
                        data="username, password_hash",
                    )
                ],
                components_involved=["comp-api", "comp-db"],
                integrations_involved=["int-01"],
            )
        ],
        test_coverage=[
            ComponentTestCoverage(
                component_id="comp-api",
                functional_coverage="adequate",
                nonfunctional_coverage="partial",
                test_types_present=["unit", "integration"],
                gaps=["No load testing"],
                evidence_locators=["tests/test_api.py"],
            )
        ],
        diagrams=[
            C4Diagram(
                level="context",
                title="System Context",
                scope="Full system",
                mermaid="graph TD\n  User-->API",
                component_ids=["comp-api"],
            )
        ],
        risk_findings=[
            RiskFinding(
                id="risk-01",
                category="performance_bottleneck",
                severity="medium",
                title="Single DB connection pool",
                description="API uses a single connection pool with no read replicas",
                affected_component_ids=["comp-db"],
                evidence="No replica config found",
                recommendation="Add read replicas for query scaling",
            ),
            RiskFinding(
                id="risk-02",
                category="security_surface",
                severity="high",
                title="No rate limiting on API",
                description="API endpoints lack rate limiting",
                affected_component_ids=["comp-api"],
                evidence="No rate-limit middleware configured",
                recommendation="Add rate limiting middleware",
            ),
        ],
        domain_model=DomainModelSection(
            entities=[
                DomainEntity(
                    name="User",
                    description="System user",
                    attributes=["id", "email", "name"],
                    relationships=[
                        EntityRelationship(
                            target_entity="Order",
                            relationship_type="has_many",
                        )
                    ],
                    bounded_context="identity",
                )
            ],
            bounded_contexts=[
                BoundedContext(
                    name="identity",
                    description="User identity and auth",
                    entities=["User"],
                    component_ids=["comp-api"],
                    upstream_contexts=[],
                    downstream_contexts=["ordering"],
                )
            ],
            context_map_mermaid="graph LR\n  identity-->ordering",
        ),
        market_analysis=MarketAnalysisSection(
            comparisons=[
                MarketComparison(
                    name="Competitor X",
                    description="Similar REST platform",
                    similarities=["REST API", "PostgreSQL backend"],
                    differences=["Uses GraphQL additionally"],
                    maturity="defined",
                    relative_positioning="More mature, larger team",
                )
            ],
            overall_maturity="developing",
            maturity_rationale="Early stage with solid foundations",
            differentiation_summary="Focused on developer experience",
        ),
        recommendations=[
            Recommendation(
                id="rec-01",
                category="additional_testing",
                priority="high",
                title="Add load tests for API",
                description="No performance tests exist for the API layer",
                rationale="Database bottleneck risk requires load characterization",
                affected_component_ids=["comp-api"],
            ),
            Recommendation(
                id="rec-02",
                category="architecture_improvement",
                priority="medium",
                title="Add read replicas",
                description="Database should have read replicas for scaling",
                rationale="Single point of failure for read traffic",
                affected_component_ids=["comp-db"],
            ),
        ],
    )


def _make_empty_report() -> ArchReport:
    """Construct a minimal report with no components, risks, etc."""
    return ArchReport(
        metadata=ArchReportMetadata(
            tool_version="0.1.0",
            timestamp="2026-05-25T12:00:00Z",
            repos_analyzed=[],
            llm_available=False,
        ),
    )


def _make_report_without_llm_sections() -> ArchReport:
    """Report with components but no domain_model or market_analysis."""
    return ArchReport(
        metadata=_make_metadata(),
        components=[
            Component(
                id="comp-svc",
                name="Service",
                description="A service",
                component_type="service",
            )
        ],
        domain_model=None,
        market_analysis=None,
    )


# ---------------------------------------------------------------------------
# JSON rendering tests
# ---------------------------------------------------------------------------


class TestRenderArchJson:
    def test_writes_valid_json(self, tmp_path: Path) -> None:
        report = _make_full_report()
        out = tmp_path / "report.json"
        result = render_arch_json(report, out)
        assert result == out
        assert out.exists()

        data = json.loads(out.read_text())
        assert isinstance(data, dict)

    def test_contains_expected_top_level_fields(self, tmp_path: Path) -> None:
        report = _make_full_report()
        out = tmp_path / "report.json"
        render_arch_json(report, out)
        data = json.loads(out.read_text())

        assert "schema_version" in data
        assert "metadata" in data
        assert "components" in data
        assert "integration_points" in data
        assert "risk_findings" in data
        assert "recommendations" in data
        assert "domain_model" in data
        assert "market_analysis" in data

    def test_roundtrip_through_arch_report(self, tmp_path: Path) -> None:
        original = _make_full_report()
        out = tmp_path / "report.json"
        render_arch_json(original, out)
        restored = ArchReport.model_validate_json(out.read_text())
        assert restored == original

    def test_empty_report_json(self, tmp_path: Path) -> None:
        report = _make_empty_report()
        out = tmp_path / "report.json"
        render_arch_json(report, out)
        data = json.loads(out.read_text())
        assert data["components"] == []
        assert data["risk_findings"] == []
        assert data["domain_model"] is None

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        out = tmp_path / "sub" / "dir" / "report.json"
        render_arch_json(_make_full_report(), out)
        assert out.exists()


# ---------------------------------------------------------------------------
# Markdown rendering tests
# ---------------------------------------------------------------------------


class TestRenderArchMarkdown:
    def test_writes_file(self, tmp_path: Path) -> None:
        report = _make_full_report()
        out = tmp_path / "report.md"
        result = render_arch_markdown(report, out)
        assert result == out
        assert out.exists()

    def test_contains_section_headers(self, tmp_path: Path) -> None:
        report = _make_full_report()
        out = tmp_path / "report.md"
        render_arch_markdown(report, out)
        content = out.read_text()

        assert "# Architecture Report" in content
        assert "## Executive Summary" in content
        assert "## Components" in content
        assert "## Integration Points" in content
        assert "## C4 Diagrams" in content
        assert "## Test Coverage" in content
        assert "## Risk Findings" in content
        assert "## Domain Model" in content
        assert "## Market Analysis" in content
        assert "## Recommendations" in content

    def test_component_table(self, tmp_path: Path) -> None:
        report = _make_full_report()
        out = tmp_path / "report.md"
        render_arch_markdown(report, out)
        content = out.read_text()

        assert "comp-api" in content
        assert "API Service" in content
        assert "comp-db" in content
        assert "Database" in content

    def test_integration_table(self, tmp_path: Path) -> None:
        report = _make_full_report()
        out = tmp_path / "report.md"
        render_arch_markdown(report, out)
        content = out.read_text()

        assert "comp-api" in content
        assert "comp-db" in content
        assert "synchronous" in content
        assert "SQL" in content

    def test_mermaid_code_blocks(self, tmp_path: Path) -> None:
        report = _make_full_report()
        out = tmp_path / "report.md"
        render_arch_markdown(report, out)
        content = out.read_text()

        assert "```mermaid" in content
        assert "graph TD" in content
        assert "User-->API" in content

    def test_risk_sections_grouped_by_severity(self, tmp_path: Path) -> None:
        report = _make_full_report()
        out = tmp_path / "report.md"
        render_arch_markdown(report, out)
        content = out.read_text()

        assert "### HIGH" in content
        assert "### MEDIUM" in content
        assert "risk-01" in content
        assert "risk-02" in content
        assert "Single DB connection pool" in content
        assert "No rate limiting" in content

    def test_recommendations_grouped_by_priority(self, tmp_path: Path) -> None:
        report = _make_full_report()
        out = tmp_path / "report.md"
        render_arch_markdown(report, out)
        content = out.read_text()

        assert "rec-01" in content
        assert "rec-02" in content
        assert "Add load tests" in content

    def test_metadata_rendered(self, tmp_path: Path) -> None:
        report = _make_full_report()
        out = tmp_path / "report.md"
        render_arch_markdown(report, out)
        content = out.read_text()

        assert "2026-05-25T12:00:00Z" in content
        assert "test-repo" in content
        assert "claude-sonnet-4-6" in content

    def test_domain_model_absent_when_none(self, tmp_path: Path) -> None:
        report = _make_report_without_llm_sections()
        out = tmp_path / "report.md"
        render_arch_markdown(report, out)
        content = out.read_text()

        assert "## Domain Model" not in content

    def test_market_analysis_absent_when_none(self, tmp_path: Path) -> None:
        report = _make_report_without_llm_sections()
        out = tmp_path / "report.md"
        render_arch_markdown(report, out)
        content = out.read_text()

        assert "## Market Analysis" not in content

    def test_domain_model_present_when_populated(self, tmp_path: Path) -> None:
        report = _make_full_report()
        out = tmp_path / "report.md"
        render_arch_markdown(report, out)
        content = out.read_text()

        assert "## Domain Model" in content
        assert "### Entities" in content
        assert "User" in content
        assert "identity" in content
        assert "### Context Map" in content
        assert "identity-->ordering" in content

    def test_market_analysis_present_when_populated(self, tmp_path: Path) -> None:
        report = _make_full_report()
        out = tmp_path / "report.md"
        render_arch_markdown(report, out)
        content = out.read_text()

        assert "## Market Analysis" in content
        assert "Competitor X" in content
        assert "developing" in content
        assert "Focused on developer experience" in content

    def test_empty_report_markdown(self, tmp_path: Path) -> None:
        report = _make_empty_report()
        out = tmp_path / "report.md"
        render_arch_markdown(report, out)
        content = out.read_text()

        assert "# Architecture Report" in content
        assert "No components discovered" in content
        assert "No integration points discovered" in content
        assert "No risks identified" in content

    def test_test_coverage_section(self, tmp_path: Path) -> None:
        report = _make_full_report()
        out = tmp_path / "report.md"
        render_arch_markdown(report, out)
        content = out.read_text()

        assert "## Test Coverage" in content
        assert "comp-api" in content
        assert "adequate" in content
        assert "No load testing" in content

    def test_executive_summary_counts(self, tmp_path: Path) -> None:
        report = _make_full_report()
        out = tmp_path / "report.md"
        render_arch_markdown(report, out)
        content = out.read_text()

        assert "**Components:** 2" in content
        assert "**Integration points:** 1" in content

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        out = tmp_path / "sub" / "dir" / "report.md"
        render_arch_markdown(_make_full_report(), out)
        assert out.exists()


# ---------------------------------------------------------------------------
# PDF rendering tests
# ---------------------------------------------------------------------------


class TestRenderArchPdf:
    def test_returns_none_without_weasyprint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When weasyprint is not importable, render_arch_pdf returns None."""
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):  # type: ignore[no-untyped-def]
            if name == "weasyprint":
                raise ImportError("no weasyprint")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        report = _make_full_report()
        out = tmp_path / "report.pdf"
        result = render_arch_pdf(report, out)
        assert result is None
        assert not out.exists()

    @pytest.fixture()
    def _requires_weasyprint(self) -> None:
        pytest.importorskip("weasyprint")

    @pytest.mark.usefixtures("_requires_weasyprint")
    def test_pdf_created(self, tmp_path: Path) -> None:
        report = _make_full_report()
        out = tmp_path / "report.pdf"
        result = render_arch_pdf(report, out)
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 0
        # PDF magic bytes
        assert out.read_bytes()[:5] == b"%PDF-"

    @pytest.mark.usefixtures("_requires_weasyprint")
    def test_pdf_empty_report(self, tmp_path: Path) -> None:
        report = _make_empty_report()
        out = tmp_path / "report.pdf"
        result = render_arch_pdf(report, out)
        assert result == out
        assert out.read_bytes()[:5] == b"%PDF-"

    @pytest.mark.usefixtures("_requires_weasyprint")
    def test_pdf_without_llm_sections(self, tmp_path: Path) -> None:
        report = _make_report_without_llm_sections()
        out = tmp_path / "report.pdf"
        result = render_arch_pdf(report, out)
        assert result == out
        assert out.exists()


# ---------------------------------------------------------------------------
# Multi-format orchestrator tests
# ---------------------------------------------------------------------------


class TestRenderArchReport:
    def test_default_formats_json_and_md(self, tmp_path: Path) -> None:
        report = _make_full_report()
        results = render_arch_report(report, tmp_path, formats=["json", "md"])

        assert "json" in results
        assert "md" in results
        assert results["json"] is not None
        assert results["md"] is not None
        assert results["json"].exists()
        assert results["md"].exists()
        assert "test-repo" in results["json"].name
        assert results["json"].name.endswith("-architecture-report.json")
        assert results["md"].name.endswith("-architecture-report.md")

    def test_explicit_formats(self, tmp_path: Path) -> None:
        report = _make_full_report()
        results = render_arch_report(report, tmp_path, formats=["json"])

        assert "json" in results
        assert "md" not in results
        assert results["json"].exists()
        md_files = list(tmp_path.glob("*-architecture-report.md"))
        assert len(md_files) == 0

    def test_unknown_format_returns_none(self, tmp_path: Path) -> None:
        report = _make_full_report()
        results = render_arch_report(report, tmp_path, formats=["xml"])

        assert results["xml"] is None

    def test_creates_output_directory(self, tmp_path: Path) -> None:
        report = _make_full_report()
        out_dir = tmp_path / "nested" / "output"
        results = render_arch_report(report, out_dir, formats=["json", "md"])

        assert out_dir.exists()
        assert results["json"] is not None
        assert results["md"] is not None

    @pytest.fixture()
    def _requires_weasyprint(self) -> None:
        pytest.importorskip("weasyprint")

    @pytest.mark.usefixtures("_requires_weasyprint")
    def test_all_three_formats(self, tmp_path: Path) -> None:
        report = _make_full_report()
        results = render_arch_report(report, tmp_path, formats=["json", "md", "pdf"])

        assert results["json"] is not None
        assert results["md"] is not None
        assert results["pdf"] is not None
        assert results["json"].exists()
        assert results["md"].exists()
        assert results["pdf"].exists()
        assert results["pdf"].name.endswith("-architecture-report.pdf")

    def test_empty_report_all_formats(self, tmp_path: Path) -> None:
        report = _make_empty_report()
        results = render_arch_report(report, tmp_path, formats=["json", "md"])

        assert results["json"] is not None
        assert results["md"] is not None
        # Verify the JSON is valid and round-trips
        json_path = results["json"]
        assert json_path is not None
        restored = ArchReport.model_validate_json(json_path.read_text())
        assert restored == report

    def test_default_formats_without_explicit_arg(self, tmp_path: Path) -> None:
        """When formats=None, at least json and md are produced."""
        report = _make_full_report()
        results = render_arch_report(report, tmp_path)

        assert "json" in results
        assert "md" in results
        assert results["json"] is not None
        assert results["md"] is not None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_html_special_chars_in_markdown(self, tmp_path: Path) -> None:
        """Components with HTML-special characters should not break markdown."""
        report = ArchReport(
            metadata=_make_metadata(),
            components=[
                Component(
                    id="comp-1",
                    name="Service <alpha>",
                    description='Uses "quotes" & ampersands',
                    component_type="service",
                )
            ],
        )
        out = tmp_path / "report.md"
        render_arch_markdown(report, out)
        content = out.read_text()
        # Content should be present (markdown doesn't require escaping)
        assert "Service <alpha>" in content
        assert '"quotes" & ampersands' in content

    def test_html_special_chars_in_json(self, tmp_path: Path) -> None:
        """JSON should handle special characters correctly."""
        report = ArchReport(
            metadata=_make_metadata(),
            components=[
                Component(
                    id="comp-1",
                    name="Service <alpha>",
                    description='Uses "quotes" & ampersands',
                    component_type="service",
                )
            ],
        )
        out = tmp_path / "report.json"
        render_arch_json(report, out)
        data = json.loads(out.read_text())
        assert data["components"][0]["name"] == "Service <alpha>"

    def test_report_with_no_protocol(self, tmp_path: Path) -> None:
        """Integration without protocol renders correctly."""
        report = ArchReport(
            metadata=_make_metadata(),
            integration_points=[
                IntegrationPoint(
                    id="int-x",
                    source_component_id="a",
                    target_component_id="b",
                    style="asynchronous",
                    protocol=None,
                    description="Async comms",
                )
            ],
        )
        out = tmp_path / "report.md"
        render_arch_markdown(report, out)
        content = out.read_text()
        assert "asynchronous" in content
        # Protocol column should show dash for None
        assert "| - |" in content

    def test_bounded_context_with_upstream_downstream(self, tmp_path: Path) -> None:
        """Bounded contexts with upstream/downstream render correctly."""
        report = ArchReport(
            metadata=_make_metadata(),
            domain_model=DomainModelSection(
                bounded_contexts=[
                    BoundedContext(
                        name="ordering",
                        description="Order management",
                        entities=["Order"],
                        component_ids=[],
                        upstream_contexts=["identity"],
                        downstream_contexts=["billing"],
                    )
                ],
            ),
        )
        out = tmp_path / "report.md"
        render_arch_markdown(report, out)
        content = out.read_text()
        assert "Upstream: identity" in content
        assert "Downstream: billing" in content
