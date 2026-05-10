"""Rule: dep-upgrade-path — N-1 ceiling detection and upgrade recommendations."""

from __future__ import annotations

import logging
from typing import Any

from packaging.version import InvalidVersion, Version

from nfr_review.dep_solver import ResolveResult, resolve_dependencies
from nfr_review.deps_dev_client import DepsDevClient
from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry

logger = logging.getLogger(__name__)

_DEPS_KINDS = frozenset(
    {
        "python-deps",
        "nodejs-deps",
        "java-deps",
        "go-deps",
        "csharp-deps",
    }
)

_KIND_TO_ECOSYSTEM: dict[str, str] = {
    "python-deps": "pypi",
    "nodejs-deps": "npm",
    "java-deps": "maven",
    "go-deps": "go",
    "csharp-deps": "nuget",
}


class DepUpgradePathRule:
    """N-1 ceiling detection with upgrade path recommendations via constraint solving."""

    id = "dep-upgrade-path"
    band: Band = 2
    required_collectors: list[str] = [
        "python-deps",
        "nodejs-deps",
        "java-deps",
        "go-deps",
        "csharp-deps",
    ]

    def __init__(
        self,
        client_factory: type[DepsDevClient] | Any = DepsDevClient,
    ) -> None:
        self._client_factory = client_factory

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        dep_evidence = [
            e
            for e in evidence
            if e.kind in _DEPS_KINDS and e.collector_name in self.required_collectors
        ]
        if not dep_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no dependency evidence available",
            )

        client = self._client_factory()
        findings: list[Finding] = []

        for ev in dep_evidence:
            ecosystem = _KIND_TO_ECOSYSTEM.get(ev.kind)
            if ecosystem is None:
                continue

            deps = ev.payload.get("dependencies", [])
            filtered = self._filter_deps(deps)
            if not filtered:
                logger.warning(
                    "All deps filtered out for %s (missing latest_version or status != ok)",
                    ev.collector_name,
                )
                continue

            latest_lookup = {d["name"]: d["latest_version"] for d in filtered}

            solver_input = [
                {"name": d["name"], "version_constraint": d.get("declared_version", "")}
                for d in filtered
            ]

            logger.info(
                "Starting upgrade-path resolution for %d deps in %s",
                len(solver_input),
                ecosystem,
            )
            result = resolve_dependencies(solver_input, client, ecosystem)
            logger.info(
                "Resolution result for %s: unsolvable=%s, optimal_set_size=%d",
                ecosystem,
                result.unsolvable,
                len(result.optimal_set),
            )

            ev_findings = self._process_result(result, latest_lookup, ev)
            findings.extend(ev_findings)

        if not findings:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no resolvable dependency sets found",
            )

        return RuleResult(rule_id=self.id, findings=findings)

    @staticmethod
    def _filter_deps(deps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            d for d in deps if d.get("deps_dev_status") == "ok" and d.get("latest_version")
        ]

    def _process_result(
        self,
        result: ResolveResult,
        latest_lookup: dict[str, str],
        ev: Evidence,
    ) -> list[Finding]:
        if result.unsolvable:
            return [
                Finding(
                    rule_id=self.id,
                    rag="red",
                    severity="critical",
                    summary=(
                        f"No upgrade path found for {ev.collector_name}: "
                        f"dependency constraints are unsolvable. "
                        f"Blocking constraints: {'; '.join(result.blocking_constraints)}"
                    ),
                    recommendation=(
                        "Review and relax version constraints to allow compatible upgrades. "
                        "Consider upgrading blocking packages individually."
                    ),
                    evidence_locator=f"upgrade-path:{ev.collector_name}",
                    collector_name=ev.collector_name,
                    collector_version=ev.collector_version,
                    confidence=0.9,
                    pattern_tag="upgrade-path-unsolvable",
                )
            ]

        stuck: list[str] = []
        for pkg, resolved_str in result.optimal_set.items():
            latest_str = latest_lookup.get(pkg)
            if latest_str is None:
                continue
            try:
                resolved_ver = Version(resolved_str)
                latest_ver = Version(latest_str)
            except InvalidVersion:
                continue
            if latest_ver.major - resolved_ver.major > 1:
                stuck.append(
                    f"{pkg} (resolved={resolved_str}, latest={latest_str}, "
                    f"gap={latest_ver.major - resolved_ver.major} majors)"
                )

        if stuck:
            return [
                Finding(
                    rule_id=self.id,
                    rag="red",
                    severity="high",
                    summary=(
                        f"Upgrade path for {ev.collector_name} cannot reach N-1 major "
                        f"for {len(stuck)} package(s): {'; '.join(stuck)}"
                    ),
                    recommendation=(
                        "These packages are stuck more than 1 major version behind latest. "
                        "Investigate transitive constraints blocking upgrades and consider "
                        "updating dependent packages first."
                    ),
                    evidence_locator=f"upgrade-path:{ev.collector_name}",
                    collector_name=ev.collector_name,
                    collector_version=ev.collector_version,
                    confidence=0.85,
                    pattern_tag="upgrade-path-n1-breach",
                )
            ]

        optimal_summary = ", ".join(
            f"{pkg}=={ver}" for pkg, ver in sorted(result.optimal_set.items())
        )
        return [
            Finding(
                rule_id=self.id,
                rag="green",
                severity="info",
                summary=(
                    f"All dependencies in {ev.collector_name} can reach N-1 major version. "
                    f"Recommended set: {optimal_summary}"
                ),
                recommendation=(
                    "Consider upgrading to the recommended version set to stay current."
                ),
                evidence_locator=f"upgrade-path:{ev.collector_name}",
                collector_name=ev.collector_name,
                collector_version=ev.collector_version,
                confidence=0.85,
                pattern_tag="upgrade-path-ok",
            )
        ]


def _register() -> None:
    if "dep-upgrade-path" not in rule_registry:
        rule_registry.register("dep-upgrade-path", DepUpgradePathRule())


_register()

__all__ = ["DepUpgradePathRule"]
