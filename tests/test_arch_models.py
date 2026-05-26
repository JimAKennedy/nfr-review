# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for architecture report data models and JSON schema."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from nfr_review.arch_models import (
    ARCH_SCHEMA_VERSION,
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
    generate_arch_schema,
)


def _make_full_report() -> ArchReport:
    """Construct a fully-populated ArchReport for testing."""
    return ArchReport(
        metadata=ArchReportMetadata(
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
        ),
        components=[
            Component(
                id="comp-api",
                name="API Service",
                description="REST API gateway",
                component_type="service",
                boundaries=[
                    ComponentBoundary(
                        boundary_type="directory",
                        path="src/api",
                    )
                ],
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
            )
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
            )
        ],
    )


class TestArchReportRoundTrip:
    """Round-trip serialization tests."""

    def test_full_report_round_trip(self) -> None:
        original = _make_full_report()
        json_str = original.model_dump_json()
        restored = ArchReport.model_validate_json(json_str)
        assert restored == original

    def test_round_trip_via_dict(self) -> None:
        original = _make_full_report()
        data = original.model_dump()
        restored = ArchReport.model_validate(data)
        assert restored == original

    def test_json_schema_includes_version(self) -> None:
        schema = ArchReport.model_json_schema()
        props = schema["properties"]
        assert "schema_version" in props
        assert props["schema_version"]["default"] == ARCH_SCHEMA_VERSION


class TestArchReportValidation:
    """Validation constraint tests."""

    def test_extra_fields_rejected(self) -> None:
        report = _make_full_report()
        data = report.model_dump()
        data["unexpected_field"] = "should fail"
        with pytest.raises(ValidationError, match="unexpected_field"):
            ArchReport.model_validate(data)

    def test_component_extra_fields_rejected(self) -> None:
        data = {
            "id": "c1",
            "name": "Test",
            "description": "desc",
            "component_type": "service",
            "bogus": True,
        }
        with pytest.raises(ValidationError, match="bogus"):
            Component.model_validate(data)

    def test_invalid_component_type_rejected(self) -> None:
        data = {
            "id": "c1",
            "name": "Test",
            "description": "desc",
            "component_type": "invalid_type",
        }
        with pytest.raises(ValidationError):
            Component.model_validate(data)

    def test_scenario_step_sequence_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            ScenarioStep(
                sequence=0,
                from_component_id="a",
                to_component_id="b",
                action="test",
            )


class TestLLMSectionsOptional:
    """LLM-dependent sections can be None."""

    def test_domain_model_none(self) -> None:
        report = _make_full_report()
        data = report.model_dump()
        data["domain_model"] = None
        restored = ArchReport.model_validate(data)
        assert restored.domain_model is None

    def test_market_analysis_none(self) -> None:
        report = _make_full_report()
        data = report.model_dump()
        data["market_analysis"] = None
        restored = ArchReport.model_validate(data)
        assert restored.market_analysis is None

    def test_both_llm_sections_none_round_trips(self) -> None:
        report = _make_full_report()
        data = report.model_dump()
        data["domain_model"] = None
        data["market_analysis"] = None
        json_str = json.dumps(data)
        restored = ArchReport.model_validate_json(json_str)
        assert restored.domain_model is None
        assert restored.market_analysis is None


class TestSchemaGeneration:
    """JSON schema generation tests."""

    def test_generate_arch_schema_returns_dict(self) -> None:
        schema = generate_arch_schema()
        assert isinstance(schema, dict)
        assert "properties" in schema
        assert "$defs" in schema

    def test_generate_arch_schema_writes_file(self, tmp_path) -> None:
        out = tmp_path / "schema.json"
        schema = generate_arch_schema(out)
        assert out.exists()
        loaded = json.loads(out.read_text())
        assert loaded == schema

    def test_schema_version_constant(self) -> None:
        assert ARCH_SCHEMA_VERSION == "1.0.0"
