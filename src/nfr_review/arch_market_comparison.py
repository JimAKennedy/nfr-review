# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Market comparison and maturity assessment for architecture documentation.

Compares the analyzed solution against similar market solutions using LLM
knowledge, and provides heuristic-based maturity assessment as a fallback
when no LLM is available.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from nfr_review.arch_models import (
    Component,
    ComponentTestCoverage,
    IntegrationPoint,
    MarketAnalysisSection,
    MarketComparison,
    MaturityLevel,
)
from nfr_review.llm_client import (
    ClaudeClient,
    LlmUnavailableError,
    serialize_evidence_bundle,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LANGUAGE_INDICATORS: dict[str, str] = {
    "pom.xml": "Java",
    "build.gradle": "Java/Kotlin",
    "build.gradle.kts": "Kotlin",
    "package.json": "JavaScript/TypeScript",
    "requirements.txt": "Python",
    "pyproject.toml": "Python",
    "setup.py": "Python",
    "Cargo.toml": "Rust",
    "go.mod": "Go",
    "Gemfile": "Ruby",
    "composer.json": "PHP",
    "mix.exs": "Elixir",
    "build.sbt": "Scala",
    "*.csproj": "C#/.NET",
    "CMakeLists.txt": "C/C++",
}

_FRAMEWORK_INDICATORS: dict[str, str] = {
    "django": "Django",
    "flask": "Flask",
    "fastapi": "FastAPI",
    "spring": "Spring",
    "express": "Express.js",
    "next": "Next.js",
    "react": "React",
    "angular": "Angular",
    "vue": "Vue.js",
    "rails": "Ruby on Rails",
    "laravel": "Laravel",
    "gin": "Gin",
    "actix": "Actix",
    "phoenix": "Phoenix",
}

_DATABASE_TYPES = frozenset({"database"})
_QUEUE_TYPES = frozenset({"queue"})

_COVERAGE_SCORE: dict[str, int] = {
    "none": 0,
    "minimal": 1,
    "partial": 2,
    "adequate": 3,
    "comprehensive": 4,
}

_MATURITY_LEVELS: list[MaturityLevel] = [
    "initial",
    "developing",
    "defined",
    "managed",
    "optimizing",
]


# ---------------------------------------------------------------------------
# 1. Solution profile extraction (no LLM needed)
# ---------------------------------------------------------------------------


def extract_solution_profile(
    components: list[Component],
    integrations: list[IntegrationPoint],
    repo_paths: list[Path],
) -> dict:
    """Extract a structured solution profile from discovered architecture.

    Identifies tech stack, domain hints, architecture style, and scale
    metrics. The returned dict is suitable for serialisation into an LLM
    prompt.

    Parameters
    ----------
    components:
        Discovered architectural components.
    integrations:
        Discovered integration points between components.
    repo_paths:
        Filesystem paths of the repositories being analyzed.
    """
    languages: set[str] = set()
    frameworks: set[str] = set()
    databases: list[str] = []
    queues: list[str] = []

    # Extract from component tech stacks
    for comp in components:
        for ts in comp.tech_stack:
            name_lower = ts.name.lower()
            if ts.role and "language" in ts.role.lower():
                languages.add(ts.name)
            elif ts.role and "framework" in ts.role.lower():
                frameworks.add(ts.name)
            # Check framework indicators
            for indicator, framework in _FRAMEWORK_INDICATORS.items():
                if indicator in name_lower:
                    frameworks.add(framework)

        if comp.component_type == "database":
            databases.append(comp.name)
        elif comp.component_type == "queue":
            queues.append(comp.name)

    # Detect languages from repo file structure
    for repo_path in repo_paths:
        if not repo_path.is_dir():
            continue
        for indicator_file, lang in _LANGUAGE_INDICATORS.items():
            if indicator_file.startswith("*"):
                # Glob pattern
                if list(repo_path.glob(indicator_file)):
                    languages.add(lang)
            else:
                if (repo_path / indicator_file).exists():
                    languages.add(lang)

    # Detect domain from repo names and package paths
    domain_hints: list[str] = []
    for repo_path in repo_paths:
        domain_hints.append(repo_path.name)
    for comp in components:
        for boundary in comp.boundaries:
            parts = Path(boundary.path).parts
            if parts:
                domain_hints.append(parts[0])

    # Determine architecture style
    service_count = sum(1 for c in components if c.component_type == "service")
    worker_count = sum(1 for c in components if c.component_type == "worker")
    gateway_count = sum(1 for c in components if c.component_type == "gateway")

    async_count = sum(
        1 for i in integrations if i.style in ("asynchronous", "event_driven", "message_queue")
    )
    sync_count = sum(1 for i in integrations if i.style in ("synchronous", "api_call", "rpc"))

    if service_count >= 3:
        arch_style = "microservices"
    elif service_count == 1 and worker_count == 0:
        arch_style = "monolith"
    elif async_count > sync_count and async_count > 0:
        arch_style = "event-driven"
    elif gateway_count > 0 and service_count >= 2:
        arch_style = "api-gateway"
    else:
        arch_style = "modular"

    # Count unique repos
    repos_involved = set()
    for comp in components:
        if comp.repo:
            repos_involved.add(comp.repo)
    for rp in repo_paths:
        repos_involved.add(rp.name)

    profile = {
        "languages": sorted(languages),
        "frameworks": sorted(frameworks),
        "databases": databases,
        "queues": queues,
        "domain_hints": domain_hints,
        "architecture_style": arch_style,
        "component_count": len(components),
        "integration_count": len(integrations),
        "repo_count": len(repos_involved),
        "component_types": sorted(
            {c.component_type for c in components},
        ),
        "integration_styles": sorted(
            {i.style for i in integrations},
        ),
    }

    logger.info(
        "Extracted solution profile: %s style, %d components, %d integrations",
        arch_style,
        len(components),
        len(integrations),
    )

    return profile


# ---------------------------------------------------------------------------
# 2. LLM-powered market comparison
# ---------------------------------------------------------------------------

_MARKET_COMPARISON_PROMPT = """\
You are an expert software architect. Analyze the following solution profile and \
compare it against similar solutions available in the market.

Respond with a JSON object (no markdown fencing) matching this exact schema:
{{
  "comparisons": [
    {{
      "name": "string — name of a real, well-known product or open-source project",
      "description": "string — one-sentence description",
      "url": "string or null — project homepage or repository URL",
      "similarities": ["string", ...],
      "differences": ["string", ...],
      "maturity": "initial | developing | defined | managed | optimizing",
      "relative_positioning": "string — how the analyzed solution compares"
    }}
  ],
  "overall_maturity": "initial | developing | defined | managed | optimizing",
  "maturity_rationale": "string — why this maturity level was chosen",
  "differentiation_summary": "string — what makes this solution unique"
}}

Guidelines:
- Identify {max_comparisons} similar market solutions (real products/projects).
- For maturity: initial=prototype, developing=early prod, defined=stable, \
managed=well-governed, optimizing=industry-leading.
- Base your assessment on the tech stack, architecture style, and scale.
- Be specific in similarities and differences.
"""


def generate_market_comparison(
    profile: dict,
    llm: ClaudeClient,
    max_comparisons: int = 5,
) -> MarketAnalysisSection:
    """Use LLM to generate market comparison analysis.

    Parameters
    ----------
    profile:
        Solution profile from :func:`extract_solution_profile`.
    llm:
        An available Claude client.
    max_comparisons:
        Maximum number of market comparisons to request.

    Returns
    -------
    MarketAnalysisSection
        Populated market analysis; comparisons list may be partial if
        the LLM response is malformed.
    """
    prompt = _MARKET_COMPARISON_PROMPT.format(max_comparisons=max_comparisons)
    evidence = serialize_evidence_bundle(
        [{"solution_profile": profile}],
        max_bytes=8192,
    )

    logger.info("Requesting market comparison from LLM (max_comparisons=%d)", max_comparisons)

    try:
        raw_response = llm.analyze(prompt, evidence, max_tokens=2048)
    except LlmUnavailableError:
        logger.warning("LLM became unavailable during market comparison")
        return MarketAnalysisSection()
    except Exception:
        logger.exception("Unexpected error during LLM market comparison")
        return MarketAnalysisSection()

    return _parse_market_response(raw_response)


def _parse_market_response(raw: str) -> MarketAnalysisSection:
    """Parse LLM JSON response into a MarketAnalysisSection.

    Handles malformed JSON gracefully by returning partial results.
    """
    # Strip markdown code fences if present
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        # Remove opening fence (possibly with language tag)
        first_newline = cleaned.index("\n")
        cleaned = cleaned[first_newline + 1 :]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("LLM returned malformed JSON for market comparison")
        return MarketAnalysisSection(
            maturity_rationale="Unable to parse LLM response",
        )

    if not isinstance(data, dict):
        logger.warning("LLM returned non-object JSON for market comparison")
        return MarketAnalysisSection(
            maturity_rationale="LLM response was not a JSON object",
        )

    # Parse comparisons
    comparisons: list[MarketComparison] = []
    for item in data.get("comparisons", []):
        if not isinstance(item, dict):
            continue
        try:
            comparisons.append(
                MarketComparison(
                    name=item.get("name", "Unknown"),
                    description=item.get("description", ""),
                    url=item.get("url"),
                    similarities=item.get("similarities", []),
                    differences=item.get("differences", []),
                    maturity=_validate_maturity(item.get("maturity", "initial")),
                    relative_positioning=item.get("relative_positioning", ""),
                )
            )
        except Exception:
            logger.warning("Skipping malformed comparison entry: %s", item.get("name", "?"))
            continue

    overall_maturity = _validate_maturity(data.get("overall_maturity", "initial"))
    maturity_rationale = data.get("maturity_rationale", "")
    differentiation_summary = data.get("differentiation_summary", "")

    return MarketAnalysisSection(
        comparisons=comparisons,
        overall_maturity=overall_maturity,
        maturity_rationale=str(maturity_rationale),
        differentiation_summary=str(differentiation_summary),
    )


def _validate_maturity(value: str) -> MaturityLevel:
    """Validate and normalise a maturity level string."""
    valid: set[str] = {"initial", "developing", "defined", "managed", "optimizing"}
    if isinstance(value, str) and value.lower().strip() in valid:
        return value.lower().strip()  # type: ignore[return-value]
    return "initial"


# ---------------------------------------------------------------------------
# 3. Heuristic-based maturity assessment (no LLM)
# ---------------------------------------------------------------------------


def generate_basic_maturity_assessment(
    components: list[Component],
    integrations: list[IntegrationPoint],
    test_coverage: list[ComponentTestCoverage],
) -> MarketAnalysisSection:
    """Generate a heuristic-based maturity assessment without LLM.

    No market comparisons are produced (those require LLM knowledge).
    The maturity level is scored based on component count, integration
    patterns, and test coverage levels.

    Parameters
    ----------
    components:
        Discovered architectural components.
    integrations:
        Discovered integration points.
    test_coverage:
        Test coverage data for components.

    Returns
    -------
    MarketAnalysisSection
        Section with empty comparisons but populated maturity fields.
    """
    score = 0.0
    rationale_parts: list[str] = []

    # --- Component maturity (0-25 points) ---
    comp_count = len(components)
    if comp_count == 0:
        comp_score = 0.0
    elif comp_count == 1:
        comp_score = 5.0
    elif comp_count <= 3:
        comp_score = 10.0
    elif comp_count <= 8:
        comp_score = 18.0
    else:
        comp_score = 25.0

    comp_types = {c.component_type for c in components}
    type_diversity = len(comp_types)
    if type_diversity >= 4:
        comp_score = min(25.0, comp_score + 5.0)

    score += comp_score
    rationale_parts.append(
        f"{comp_count} components ({type_diversity} types) "
        f"-> {comp_score:.0f}/25 component score"
    )

    # --- Integration maturity (0-25 points) ---
    intg_count = len(integrations)
    intg_styles = {i.style for i in integrations}
    style_count = len(intg_styles)

    if intg_count == 0:
        intg_score = 0.0
    elif intg_count <= 2:
        intg_score = 8.0
    elif intg_count <= 6:
        intg_score = 15.0
    else:
        intg_score = 20.0

    # Bonus for diverse integration styles
    if style_count >= 3:
        intg_score = min(25.0, intg_score + 5.0)

    score += intg_score
    rationale_parts.append(
        f"{intg_count} integrations ({style_count} styles) "
        f"-> {intg_score:.0f}/25 integration score"
    )

    # --- Test coverage maturity (0-30 points) ---
    if test_coverage:
        func_scores = [_COVERAGE_SCORE.get(tc.functional_coverage, 0) for tc in test_coverage]
        nf_scores = [_COVERAGE_SCORE.get(tc.nonfunctional_coverage, 0) for tc in test_coverage]
        avg_func = sum(func_scores) / len(func_scores)
        avg_nf = sum(nf_scores) / len(nf_scores)

        # Functional coverage: 0-15 points
        func_score = min(15.0, avg_func * 3.75)
        # Non-functional coverage: 0-15 points
        nf_score = min(15.0, avg_nf * 3.75)
        test_score = func_score + nf_score
    else:
        test_score = 0.0
        avg_func = 0.0
        avg_nf = 0.0

    score += test_score
    rationale_parts.append(
        f"Test coverage (func avg={avg_func:.1f}, nf avg={avg_nf:.1f}) -> "
        f"{test_score:.0f}/30 test score"
    )

    # --- Structure maturity (0-20 points) ---
    has_gateway = any(c.component_type == "gateway" for c in components)
    has_worker = any(c.component_type == "worker" for c in components)
    has_queue = any(c.component_type == "queue" for c in components)
    has_db = any(c.component_type == "database" for c in components)
    has_async = any(
        i.style in ("asynchronous", "event_driven", "message_queue") for i in integrations
    )

    struct_score = 0.0
    if has_gateway:
        struct_score += 5.0
    if has_worker:
        struct_score += 4.0
    if has_queue:
        struct_score += 4.0
    if has_db:
        struct_score += 3.0
    if has_async:
        struct_score += 4.0
    struct_score = min(20.0, struct_score)

    score += struct_score
    rationale_parts.append(f"Structure features -> {struct_score:.0f}/20 structure score")

    # --- Map score to maturity level ---
    total = min(100.0, score)
    if total >= 80:
        maturity: MaturityLevel = "optimizing"
    elif total >= 60:
        maturity = "managed"
    elif total >= 40:
        maturity = "defined"
    elif total >= 20:
        maturity = "developing"
    else:
        maturity = "initial"

    rationale = f"Total score: {total:.0f}/100. " + "; ".join(rationale_parts) + "."

    logger.info("Basic maturity assessment: %s (score=%.0f)", maturity, total)

    return MarketAnalysisSection(
        comparisons=[],
        overall_maturity=maturity,
        maturity_rationale=rationale,
        differentiation_summary=(
            "Maturity assessed via heuristic analysis of component structure, "
            "integration patterns, and test coverage. No market comparisons "
            "available without LLM."
        ),
    )


# ---------------------------------------------------------------------------
# 4. Top-level orchestrator
# ---------------------------------------------------------------------------


def analyze_market(
    repo_paths: list[Path],
    components: list[Component],
    integrations: list[IntegrationPoint],
    test_coverage: list[ComponentTestCoverage],
    llm: ClaudeClient | None = None,
) -> MarketAnalysisSection | None:
    """Run market comparison analysis.

    Uses LLM-powered comparison when available, falling back to heuristic
    maturity assessment otherwise. Returns ``None`` when there are no
    components to analyze.

    Parameters
    ----------
    repo_paths:
        Filesystem paths of the repositories being analyzed.
    components:
        Discovered architectural components.
    integrations:
        Discovered integration points.
    test_coverage:
        Test coverage data for components.
    llm:
        Optional Claude client for LLM-powered comparison.

    Returns
    -------
    MarketAnalysisSection or None
        ``None`` only when *components* is empty.
    """
    if not components:
        logger.info("No components provided; skipping market analysis")
        return None

    logger.info(
        "Starting market analysis: %d components, llm=%s",
        len(components),
        "available" if llm and llm.available else "unavailable",
    )

    if llm is not None and llm.available:
        profile = extract_solution_profile(components, integrations, repo_paths)
        result = generate_market_comparison(profile, llm)
        # If LLM returned an empty result, supplement with basic assessment
        if not result.comparisons and not result.maturity_rationale:
            logger.info("LLM returned empty result; falling back to basic assessment")
            result = generate_basic_maturity_assessment(
                components, integrations, test_coverage
            )
        return result

    logger.info("LLM unavailable; using basic maturity assessment")
    return generate_basic_maturity_assessment(components, integrations, test_coverage)


__all__ = [
    "analyze_market",
    "extract_solution_profile",
    "generate_basic_maturity_assessment",
    "generate_market_comparison",
]
