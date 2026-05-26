# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for market comparison and maturity assessment."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock

import pytest

from nfr_review.arch_market_comparison import (
    _parse_market_response,
    _validate_maturity,
    analyze_market,
    extract_solution_profile,
    generate_basic_maturity_assessment,
    generate_market_comparison,
)
from nfr_review.arch_models import (
    Component,
    ComponentBoundary,
    ComponentTestCoverage,
    IntegrationPoint,
    MarketAnalysisSection,
    TechStackEntry,
)
from nfr_review.llm_client import LlmUnavailableError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_component(
    name: str,
    comp_type: str = "service",
    repo: str = "test-repo",
    tech_stack: list[TechStackEntry] | None = None,
) -> Component:
    """Create a minimal Component for testing."""
    return Component(
        id=f"comp-{name}",
        name=name,
        description=f"Test component {name}",
        component_type=comp_type,
        boundaries=[
            ComponentBoundary(
                boundary_type="directory",
                path=name,
                repo=repo,
            )
        ],
        repo=repo,
        tech_stack=tech_stack or [],
    )


def _make_integration(
    source: str,
    target: str,
    style: str = "synchronous",
    is_cross_repo: bool = False,
) -> IntegrationPoint:
    """Create a minimal IntegrationPoint for testing."""
    return IntegrationPoint(
        id=f"intg-{source}-{target}",
        source_component_id=f"comp-{source}",
        target_component_id=f"comp-{target}",
        style=style,
        description=f"{source} -> {target}",
        is_cross_repo=is_cross_repo,
    )


def _make_coverage(
    component_name: str,
    functional: str = "adequate",
    nonfunctional: str = "partial",
    test_types: list[str] | None = None,
    gaps: list[str] | None = None,
) -> ComponentTestCoverage:
    """Create a minimal ComponentTestCoverage for testing."""
    return ComponentTestCoverage(
        component_id=f"comp-{component_name}",
        functional_coverage=functional,
        nonfunctional_coverage=nonfunctional,
        test_types_present=test_types or ["unit", "integration"],
        gaps=gaps or [],
    )


def _make_llm_mock(available: bool = True, response: str = "{}") -> MagicMock:
    """Create a mock ClaudeClient."""
    mock = MagicMock()
    type(mock).available = PropertyMock(return_value=available)
    mock.analyze.return_value = response
    return mock


def _make_valid_llm_response(
    num_comparisons: int = 3,
    overall_maturity: str = "defined",
) -> str:
    """Build a valid JSON response as an LLM would return."""
    comparisons = []
    for i in range(num_comparisons):
        comparisons.append(
            {
                "name": f"Product-{i + 1}",
                "description": f"Description for product {i + 1}",
                "url": f"https://example.com/product-{i + 1}",
                "similarities": [f"similarity-{i + 1}-a", f"similarity-{i + 1}-b"],
                "differences": [f"difference-{i + 1}-a"],
                "maturity": "managed",
                "relative_positioning": (
                    f"The analyzed solution is comparable to Product-{i + 1}"
                ),
            }
        )
    return json.dumps(
        {
            "comparisons": comparisons,
            "overall_maturity": overall_maturity,
            "maturity_rationale": "Based on architecture and coverage analysis",
            "differentiation_summary": "Unique due to its modular design",
        }
    )


# ---------------------------------------------------------------------------
# Tests: extract_solution_profile
# ---------------------------------------------------------------------------


class TestExtractSolutionProfile:
    """Tests for solution profile extraction."""

    def test_basic_profile(self, tmp_path: Path) -> None:
        """Profile captures component types and counts."""
        components = [
            _make_component("api", "service"),
            _make_component("db", "database"),
            _make_component("worker", "worker"),
        ]
        integrations = [
            _make_integration("api", "db", "api_call"),
            _make_integration("api", "worker", "message_queue"),
        ]

        profile = extract_solution_profile(components, integrations, [tmp_path])

        assert profile["component_count"] == 3
        assert profile["integration_count"] == 2
        assert "service" in profile["component_types"]
        assert "database" in profile["component_types"]
        assert profile["databases"] == ["db"]

    def test_detects_languages_from_files(self, tmp_path: Path) -> None:
        """Profile detects languages from build files in repos."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        (tmp_path / "package.json").write_text('{"name": "test"}')

        profile = extract_solution_profile([], [], [tmp_path])

        assert "Python" in profile["languages"]
        assert "JavaScript/TypeScript" in profile["languages"]

    def test_detects_frameworks_from_tech_stack(self) -> None:
        """Profile detects frameworks from component tech_stack entries."""
        comp = _make_component(
            "api",
            tech_stack=[
                TechStackEntry(name="fastapi", role="framework"),
            ],
        )

        profile = extract_solution_profile([comp], [], [])

        assert "FastAPI" in profile["frameworks"]

    def test_microservices_style_detection(self) -> None:
        """Architecture style is microservices with 3+ services."""
        components = [
            _make_component("svc-a", "service"),
            _make_component("svc-b", "service"),
            _make_component("svc-c", "service"),
        ]

        profile = extract_solution_profile(components, [], [])

        assert profile["architecture_style"] == "microservices"

    def test_monolith_style_detection(self) -> None:
        """Architecture style is monolith with 1 service, no workers."""
        components = [_make_component("app", "service")]

        profile = extract_solution_profile(components, [], [])

        assert profile["architecture_style"] == "monolith"

    def test_event_driven_style_detection(self) -> None:
        """Architecture style is event-driven when async > sync."""
        components = [
            _make_component("pub", "service"),
            _make_component("sub", "worker"),
        ]
        integrations = [
            _make_integration("pub", "sub", "event_driven"),
            _make_integration("pub", "sub", "message_queue"),
        ]

        profile = extract_solution_profile(components, integrations, [])

        assert profile["architecture_style"] == "event-driven"

    def test_queues_captured(self) -> None:
        """Queues are captured from queue-type components."""
        components = [
            _make_component("rabbitmq", "queue"),
            _make_component("api", "service"),
        ]

        profile = extract_solution_profile(components, [], [])

        assert profile["queues"] == ["rabbitmq"]

    def test_repo_count(self, tmp_path: Path) -> None:
        """Repo count includes repo_paths and component repos."""
        components = [
            _make_component("api", repo="repo-a"),
            _make_component("worker", repo="repo-b"),
        ]

        profile = extract_solution_profile(components, [], [tmp_path])

        # tmp_path.name + repo-a + repo-b
        assert profile["repo_count"] >= 2

    def test_empty_inputs(self) -> None:
        """Profile is well-formed with empty inputs."""
        profile = extract_solution_profile([], [], [])

        assert profile["component_count"] == 0
        assert profile["integration_count"] == 0
        assert profile["architecture_style"] == "modular"
        assert profile["languages"] == []
        assert profile["frameworks"] == []

    def test_domain_hints_from_repo_path(self, tmp_path: Path) -> None:
        """Domain hints include repository names."""
        profile = extract_solution_profile([], [], [tmp_path])

        assert tmp_path.name in profile["domain_hints"]


# ---------------------------------------------------------------------------
# Tests: LLM-powered comparison
# ---------------------------------------------------------------------------


class TestGenerateMarketComparison:
    """Tests for LLM-based market comparison."""

    def test_valid_response(self) -> None:
        """Well-formed LLM response produces complete MarketAnalysisSection."""
        llm = _make_llm_mock(response=_make_valid_llm_response(3, "defined"))
        profile = {"architecture_style": "microservices", "component_count": 5}

        result = generate_market_comparison(profile, llm, max_comparisons=3)

        assert isinstance(result, MarketAnalysisSection)
        assert len(result.comparisons) == 3
        assert result.overall_maturity == "defined"
        assert result.maturity_rationale != ""
        assert result.differentiation_summary != ""
        llm.analyze.assert_called_once()

    def test_comparison_details(self) -> None:
        """Each comparison has expected fields populated."""
        llm = _make_llm_mock(response=_make_valid_llm_response(2))
        profile = {"architecture_style": "monolith"}

        result = generate_market_comparison(profile, llm)

        comp = result.comparisons[0]
        assert comp.name == "Product-1"
        assert comp.url is not None
        assert len(comp.similarities) > 0
        assert len(comp.differences) > 0
        assert comp.maturity == "managed"
        assert comp.relative_positioning != ""

    def test_max_comparisons_in_prompt(self) -> None:
        """max_comparisons value is included in the LLM prompt."""
        llm = _make_llm_mock(response=_make_valid_llm_response(1))
        profile = {"architecture_style": "monolith"}

        generate_market_comparison(profile, llm, max_comparisons=7)

        prompt_arg = llm.analyze.call_args[0][0]
        assert "7" in prompt_arg

    def test_llm_unavailable_error(self) -> None:
        """LlmUnavailableError produces empty section."""
        llm = _make_llm_mock()
        llm.analyze.side_effect = LlmUnavailableError("no key")
        profile = {}

        result = generate_market_comparison(profile, llm)

        assert isinstance(result, MarketAnalysisSection)
        assert result.comparisons == []

    def test_llm_unexpected_error(self) -> None:
        """Unexpected errors produce empty section."""
        llm = _make_llm_mock()
        llm.analyze.side_effect = RuntimeError("connection lost")
        profile = {}

        result = generate_market_comparison(profile, llm)

        assert isinstance(result, MarketAnalysisSection)
        assert result.comparisons == []


# ---------------------------------------------------------------------------
# Tests: _parse_market_response
# ---------------------------------------------------------------------------


class TestParseMarketResponse:
    """Tests for parsing LLM JSON responses."""

    def test_valid_json(self) -> None:
        """Valid JSON is parsed correctly."""
        raw = _make_valid_llm_response(2, "managed")

        result = _parse_market_response(raw)

        assert len(result.comparisons) == 2
        assert result.overall_maturity == "managed"

    def test_json_with_markdown_fences(self) -> None:
        """JSON wrapped in markdown code fences is parsed correctly."""
        inner = _make_valid_llm_response(1)
        raw = f"```json\n{inner}\n```"

        result = _parse_market_response(raw)

        assert len(result.comparisons) == 1

    def test_malformed_json(self) -> None:
        """Malformed JSON returns empty section with rationale."""
        result = _parse_market_response("this is not json {{{")

        assert isinstance(result, MarketAnalysisSection)
        assert result.comparisons == []
        assert "Unable to parse" in result.maturity_rationale

    def test_json_array_instead_of_object(self) -> None:
        """JSON array instead of object returns empty section."""
        result = _parse_market_response("[1, 2, 3]")

        assert result.comparisons == []
        assert "not a JSON object" in result.maturity_rationale

    def test_partial_comparisons(self) -> None:
        """Valid comparisons are kept even if some are malformed."""
        data = {
            "comparisons": [
                {
                    "name": "Good Product",
                    "description": "A real product",
                    "maturity": "managed",
                },
                42,  # not a dict — skipped
                {
                    "name": "Another Product",
                    "description": "Also real",
                },
            ],
            "overall_maturity": "defined",
            "maturity_rationale": "test",
            "differentiation_summary": "test diff",
        }
        raw = json.dumps(data)

        result = _parse_market_response(raw)

        assert len(result.comparisons) == 2
        assert result.comparisons[0].name == "Good Product"
        assert result.comparisons[1].name == "Another Product"

    def test_invalid_maturity_level_defaults(self) -> None:
        """Invalid maturity values default to 'initial'."""
        data = {
            "comparisons": [],
            "overall_maturity": "super_advanced",
            "maturity_rationale": "test",
            "differentiation_summary": "",
        }

        result = _parse_market_response(json.dumps(data))

        assert result.overall_maturity == "initial"

    def test_empty_object(self) -> None:
        """Empty JSON object produces valid empty section."""
        result = _parse_market_response("{}")

        assert isinstance(result, MarketAnalysisSection)
        assert result.comparisons == []
        assert result.overall_maturity == "initial"


# ---------------------------------------------------------------------------
# Tests: _validate_maturity
# ---------------------------------------------------------------------------


class TestValidateMaturity:
    """Tests for maturity level validation."""

    @pytest.mark.parametrize(
        "input_val,expected",
        [
            ("initial", "initial"),
            ("developing", "developing"),
            ("defined", "defined"),
            ("managed", "managed"),
            ("optimizing", "optimizing"),
            ("INITIAL", "initial"),
            ("  Defined  ", "defined"),
        ],
    )
    def test_valid_levels(self, input_val: str, expected: str) -> None:
        assert _validate_maturity(input_val) == expected

    @pytest.mark.parametrize(
        "input_val",
        ["invalid", "advanced", "", "123", "none"],
    )
    def test_invalid_levels_default_to_initial(self, input_val: str) -> None:
        assert _validate_maturity(input_val) == "initial"


# ---------------------------------------------------------------------------
# Tests: generate_basic_maturity_assessment
# ---------------------------------------------------------------------------


class TestGenerateBasicMaturityAssessment:
    """Tests for heuristic maturity assessment."""

    def test_minimal_system(self) -> None:
        """Single component, no integrations, no coverage -> low maturity."""
        components = [_make_component("app")]
        result = generate_basic_maturity_assessment(components, [], [])

        assert isinstance(result, MarketAnalysisSection)
        assert result.comparisons == []
        assert result.overall_maturity in ("initial", "developing")
        assert result.maturity_rationale != ""
        assert "heuristic" in result.differentiation_summary.lower()

    def test_well_structured_system(self) -> None:
        """Complex system with good coverage -> higher maturity."""
        components = [
            _make_component("gateway", "gateway"),
            _make_component("api-a", "service"),
            _make_component("api-b", "service"),
            _make_component("api-c", "service"),
            _make_component("worker", "worker"),
            _make_component("queue", "queue"),
            _make_component("db", "database"),
            _make_component("ui", "ui"),
            _make_component("cache", "service"),
        ]
        integrations = [
            _make_integration("gateway", "api-a", "api_call"),
            _make_integration("gateway", "api-b", "api_call"),
            _make_integration("gateway", "api-c", "api_call"),
            _make_integration("api-a", "db", "synchronous"),
            _make_integration("api-b", "db", "synchronous"),
            _make_integration("api-c", "queue", "message_queue"),
            _make_integration("queue", "worker", "asynchronous"),
        ]
        coverage = [
            _make_coverage("gateway", "comprehensive", "adequate"),
            _make_coverage("api-a", "comprehensive", "comprehensive"),
            _make_coverage("api-b", "adequate", "partial"),
            _make_coverage("api-c", "adequate", "adequate"),
            _make_coverage("worker", "adequate", "partial"),
        ]

        result = generate_basic_maturity_assessment(components, integrations, coverage)

        # Should be at least "managed" with this setup
        assert result.overall_maturity in ("managed", "optimizing")

    def test_no_test_coverage(self) -> None:
        """System without test coverage scores lower."""
        components = [
            _make_component("api", "service"),
            _make_component("db", "database"),
        ]
        integrations = [_make_integration("api", "db", "api_call")]

        result = generate_basic_maturity_assessment(components, integrations, [])

        # Without coverage data, test score is 0
        assert result.overall_maturity in ("initial", "developing")

    def test_empty_inputs(self) -> None:
        """Empty inputs produce initial maturity."""
        result = generate_basic_maturity_assessment([], [], [])

        assert result.overall_maturity == "initial"
        assert result.comparisons == []

    def test_rationale_includes_scores(self) -> None:
        """Rationale includes component and test score breakdowns."""
        components = [_make_component("api")]
        result = generate_basic_maturity_assessment(components, [], [])

        assert "component score" in result.maturity_rationale
        assert "integration score" in result.maturity_rationale
        assert "test score" in result.maturity_rationale

    def test_diverse_integration_styles_bonus(self) -> None:
        """Diverse integration styles earn bonus points."""
        components = [
            _make_component("a", "service"),
            _make_component("b", "service"),
            _make_component("c", "service"),
            _make_component("d", "worker"),
        ]
        integrations_basic = [
            _make_integration("a", "b", "synchronous"),
            _make_integration("b", "c", "synchronous"),
            _make_integration("c", "d", "synchronous"),
        ]
        integrations_diverse = [
            _make_integration("a", "b", "synchronous"),
            _make_integration("b", "c", "event_driven"),
            _make_integration("c", "d", "message_queue"),
        ]

        result_basic = generate_basic_maturity_assessment(components, integrations_basic, [])
        result_diverse = generate_basic_maturity_assessment(
            components, integrations_diverse, []
        )

        # The "diverse" version should score at least as high
        maturity_order = ["initial", "developing", "defined", "managed", "optimizing"]
        idx_basic = maturity_order.index(result_basic.overall_maturity)
        idx_diverse = maturity_order.index(result_diverse.overall_maturity)
        assert idx_diverse >= idx_basic


# ---------------------------------------------------------------------------
# Tests: analyze_market (orchestrator)
# ---------------------------------------------------------------------------


class TestAnalyzeMarket:
    """Tests for the top-level orchestrator."""

    def test_empty_components_returns_none(self, tmp_path: Path) -> None:
        """No components -> returns None."""
        result = analyze_market(
            repo_paths=[tmp_path],
            components=[],
            integrations=[],
            test_coverage=[],
        )

        assert result is None

    def test_with_llm(self, tmp_path: Path) -> None:
        """With an available LLM, uses LLM path."""
        llm = _make_llm_mock(response=_make_valid_llm_response(2, "managed"))
        components = [_make_component("api")]
        integrations = [_make_integration("api", "api", "synchronous")]

        result = analyze_market(
            repo_paths=[tmp_path],
            components=components,
            integrations=integrations,
            test_coverage=[],
            llm=llm,
        )

        assert result is not None
        assert len(result.comparisons) == 2
        assert result.overall_maturity == "managed"
        llm.analyze.assert_called_once()

    def test_without_llm_uses_basic(self, tmp_path: Path) -> None:
        """Without LLM, falls back to basic maturity assessment."""
        components = [_make_component("api")]

        result = analyze_market(
            repo_paths=[tmp_path],
            components=components,
            integrations=[],
            test_coverage=[],
            llm=None,
        )

        assert result is not None
        assert result.comparisons == []
        assert result.overall_maturity != ""

    def test_unavailable_llm_uses_basic(self, tmp_path: Path) -> None:
        """LLM present but unavailable falls back to basic assessment."""
        llm = _make_llm_mock(available=False)
        components = [_make_component("api")]

        result = analyze_market(
            repo_paths=[tmp_path],
            components=components,
            integrations=[],
            test_coverage=[],
            llm=llm,
        )

        assert result is not None
        assert result.comparisons == []
        # Should NOT have called analyze
        llm.analyze.assert_not_called()

    def test_llm_failure_fallback(self, tmp_path: Path) -> None:
        """When LLM raises an error, gets an empty section from generate_market_comparison,
        then falls back to basic assessment."""
        llm = _make_llm_mock()
        llm.analyze.side_effect = RuntimeError("boom")
        components = [_make_component("api")]

        result = analyze_market(
            repo_paths=[tmp_path],
            components=components,
            integrations=[],
            test_coverage=[],
            llm=llm,
        )

        assert result is not None
        # The error path in generate_market_comparison returns empty section
        # Then analyze_market falls back to basic assessment since
        # both comparisons and maturity_rationale are empty
        assert result.maturity_rationale != ""

    def test_passes_test_coverage_to_basic(self, tmp_path: Path) -> None:
        """Test coverage is used in basic assessment when LLM is unavailable."""
        components = [_make_component("api")]
        coverage = [_make_coverage("api", "comprehensive", "comprehensive")]

        result = analyze_market(
            repo_paths=[tmp_path],
            components=components,
            integrations=[],
            test_coverage=coverage,
            llm=None,
        )

        assert result is not None
        assert "test score" in result.maturity_rationale
