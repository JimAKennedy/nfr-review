# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Pydantic v2 data models for architecture documentation reports."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ARCH_SCHEMA_VERSION = "1.0.0"

# --- Type aliases ---

C4Level = Literal["context", "container", "component", "code"]
RiskCategory = Literal[
    "performance_bottleneck",
    "resilience_threat",
    "change_hotspot",
    "scalability_limit",
    "security_surface",
    "operational_risk",
]
IntegrationStyle = Literal[
    "synchronous",
    "asynchronous",
    "event_driven",
    "shared_database",
    "file_transfer",
    "api_call",
    "message_queue",
    "rpc",
    "build_dependency",
]
CoverageLevel = Literal["none", "minimal", "partial", "adequate", "comprehensive"]
MaturityLevel = Literal["initial", "developing", "defined", "managed", "optimizing"]


# --- Supporting models ---


class TechStackEntry(BaseModel):
    """A technology used by a component."""

    model_config = ConfigDict(extra="forbid")

    name: str
    version: str | None = None
    role: str | None = None


class ComponentBoundary(BaseModel):
    """How a component is bounded within the codebase."""

    model_config = ConfigDict(extra="forbid")

    boundary_type: Literal["package", "module", "directory", "build_target", "repo"]
    path: str
    repo: str | None = None


class Component(BaseModel):
    """A major architectural component discovered in the solution."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str
    component_type: Literal[
        "service", "library", "database", "queue", "gateway", "ui", "worker", "external"
    ]
    boundaries: list[ComponentBoundary] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    tech_stack: list[TechStackEntry] = Field(default_factory=list)
    repo: str | None = None
    environment: str | None = None
    c4_level: C4Level = "component"


class IntegrationPoint(BaseModel):
    """An integration between two components."""

    model_config = ConfigDict(extra="forbid")

    id: str
    source_component_id: str
    target_component_id: str
    style: IntegrationStyle
    protocol: str | None = None
    description: str = ""
    data_flow: str | None = None
    is_cross_repo: bool = False
    environment: str | None = None


class ScenarioStep(BaseModel):
    """A single step in a dynamic scenario."""

    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1)
    from_component_id: str
    to_component_id: str
    action: str
    data: str | None = None


class DynamicScenario(BaseModel):
    """A key dynamic interaction scenario through the architecture."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str
    trigger: str
    steps: list[ScenarioStep] = Field(default_factory=list)
    components_involved: list[str] = Field(default_factory=list)
    integrations_involved: list[str] = Field(default_factory=list)


class ComponentTestCoverage(BaseModel):
    """Test coverage assessment for a component."""

    model_config = ConfigDict(extra="forbid")

    component_id: str
    functional_coverage: CoverageLevel = "none"
    nonfunctional_coverage: CoverageLevel = "none"
    test_types_present: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    evidence_locators: list[str] = Field(default_factory=list)


class C4Diagram(BaseModel):
    """A C4 architecture diagram at a specific level."""

    model_config = ConfigDict(extra="forbid")

    level: C4Level
    title: str
    scope: str | None = None
    mermaid: str
    component_ids: list[str] = Field(default_factory=list)


class RiskFinding(BaseModel):
    """An architecture-level risk finding."""

    model_config = ConfigDict(extra="forbid")

    id: str
    category: RiskCategory
    severity: Literal["critical", "high", "medium", "low"]
    title: str
    description: str
    affected_component_ids: list[str] = Field(default_factory=list)
    affected_integration_ids: list[str] = Field(default_factory=list)
    evidence: str = ""
    recommendation: str = ""


class EntityRelationship(BaseModel):
    """A relationship between domain entities."""

    model_config = ConfigDict(extra="forbid")

    target_entity: str
    relationship_type: Literal[
        "has_many", "has_one", "belongs_to", "many_to_many", "references", "extends"
    ]
    description: str = ""


class DomainEntity(BaseModel):
    """An entity in the inferred domain model."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    attributes: list[str] = Field(default_factory=list)
    relationships: list[EntityRelationship] = Field(default_factory=list)
    bounded_context: str | None = None


class BoundedContext(BaseModel):
    """A bounded context in the domain model."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    entities: list[str] = Field(default_factory=list)
    component_ids: list[str] = Field(default_factory=list)
    upstream_contexts: list[str] = Field(default_factory=list)
    downstream_contexts: list[str] = Field(default_factory=list)


class MarketComparison(BaseModel):
    """Comparison with a similar solution on the market."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    url: str | None = None
    similarities: list[str] = Field(default_factory=list)
    differences: list[str] = Field(default_factory=list)
    maturity: MaturityLevel = "initial"
    relative_positioning: str = ""


class Recommendation(BaseModel):
    """A recommendation for human reviewers or additional testing."""

    model_config = ConfigDict(extra="forbid")

    id: str
    category: Literal[
        "human_review",
        "additional_testing",
        "architecture_improvement",
        "documentation_gap",
    ]
    priority: Literal["critical", "high", "medium", "low"]
    title: str
    description: str
    rationale: str
    affected_component_ids: list[str] = Field(default_factory=list)


# --- LLM-dependent sections (None when LLM unavailable) ---


class DomainModelSection(BaseModel):
    """Domain model analysis section (requires LLM)."""

    model_config = ConfigDict(extra="forbid")

    entities: list[DomainEntity] = Field(default_factory=list)
    bounded_contexts: list[BoundedContext] = Field(default_factory=list)
    context_map_mermaid: str | None = None


class MarketAnalysisSection(BaseModel):
    """Market comparison section (requires LLM)."""

    model_config = ConfigDict(extra="forbid")

    comparisons: list[MarketComparison] = Field(default_factory=list)
    overall_maturity: MaturityLevel = "initial"
    maturity_rationale: str = ""
    differentiation_summary: str = ""


# --- Root report model ---


class RepoInfo(BaseModel):
    """Information about a repository that was analyzed."""

    model_config = ConfigDict(extra="forbid")

    path: str
    name: str
    git_sha: str | None = None
    git_branch: str | None = None


class ArchReportMetadata(BaseModel):
    """Provenance and scope metadata for the architecture report."""

    model_config = ConfigDict(extra="forbid")

    tool_version: str
    schema_version: str = ARCH_SCHEMA_VERSION
    timestamp: str
    repos_analyzed: list[RepoInfo] = Field(default_factory=list)
    llm_available: bool = False
    llm_model: str | None = None


class ArchReport(BaseModel):
    """Root model for a complete architecture documentation report."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = ARCH_SCHEMA_VERSION
    metadata: ArchReportMetadata
    components: list[Component] = Field(default_factory=list)
    integration_points: list[IntegrationPoint] = Field(default_factory=list)
    dynamic_scenarios: list[DynamicScenario] = Field(default_factory=list)
    test_coverage: list[ComponentTestCoverage] = Field(default_factory=list)
    diagrams: list[C4Diagram] = Field(default_factory=list)
    risk_findings: list[RiskFinding] = Field(default_factory=list)
    domain_model: DomainModelSection | None = None
    market_analysis: MarketAnalysisSection | None = None
    recommendations: list[Recommendation] = Field(default_factory=list)


# --- Schema generation ---


def generate_arch_schema(output_path: Path | None = None) -> dict[str, Any]:
    """Generate JSON schema for ArchReport and optionally write to file."""
    schema = ArchReport.model_json_schema()
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(schema, indent=2) + "\n")
    return schema


def _main() -> None:
    """CLI entry point: generate schema to default location or stdout."""
    default_path = Path(__file__).parent / "arch-report-schema.json"
    if "--stdout" in sys.argv:
        schema = generate_arch_schema()
        json.dump(schema, sys.stdout, indent=2)
        sys.stdout.write(
            "\n"
        )  # nfr-review:skip(logging-to-stdout) reason: CLI output, not logging
    else:
        generate_arch_schema(default_path)
        print(
            f"Schema written to {default_path}"
        )  # nfr-review:skip(logging-to-stdout) reason: CLI output, not logging


if __name__ == "__main__":
    _main()


__all__ = [
    "ARCH_SCHEMA_VERSION",
    "ArchReport",
    "ArchReportMetadata",
    "BoundedContext",
    "C4Diagram",
    "C4Level",
    "Component",
    "ComponentBoundary",
    "CoverageLevel",
    "DomainEntity",
    "DomainModelSection",
    "DynamicScenario",
    "EntityRelationship",
    "IntegrationPoint",
    "IntegrationStyle",
    "MarketAnalysisSection",
    "MarketComparison",
    "MaturityLevel",
    "Recommendation",
    "RepoInfo",
    "RiskCategory",
    "RiskFinding",
    "ScenarioStep",
    "TechStackEntry",
    "ComponentTestCoverage",
    "generate_arch_schema",
]
