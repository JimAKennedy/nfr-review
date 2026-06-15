# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""PATCH-DEPS rules — dependency blast-radius readiness for safe patching.

PATCH-DEPS-001: Dependency declaration detection.
    GREEN  if workloads carry dependency annotations (app.kubernetes.io/part-of,
           backstage.io/techdocs-ref, or custom dependency-related annotations).
    AMBER  if workloads exist but no dependency annotations detected.
    SKIPPED when no k8s-manifest evidence available.

PATCH-DEPS-002: Shared-fate indicator detection.
    AMBER  if multiple deployments share the same nodeSelector values or
           container env vars pointing to the same database host.
    GREEN  if no shared-fate indicators detected among workloads.
    SKIPPED when no k8s-manifest evidence available.

PATCH-DEPS-003: Cross-ring dependency direction check.
    AMBER  if a higher-ring workload's env vars reference a lower-ring service.
    GREEN  if ring labels present and no cross-ring violations detected.
    INFO   if no ring labels found on any workload.
    SKIPPED when no k8s-manifest evidence available.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

_DEPENDENCY_ANNOTATION_PREFIXES = (
    "app.kubernetes.io/part-of",
    "backstage.io/techdocs-ref",
    "backstage.io/system",
    "dependencies/",
    "depends-on",
)

_RING_LABEL_KEYS = frozenset(
    {
        "ring",
        "app.kubernetes.io/ring",
        "deployment-ring",
        "patching-ring",
    }
)

_DB_HOST_PATTERNS = frozenset(
    {
        "DB_HOST",
        "DATABASE_HOST",
        "DATABASE_URL",
        "DB_URL",
        "POSTGRES_HOST",
        "MYSQL_HOST",
        "MONGO_HOST",
        "REDIS_HOST",
    }
)

_COLLECTOR = "k8s-manifest"


def _workload_evidence(evidence: list[Evidence]) -> list[Evidence]:
    return filter_evidence(evidence, _COLLECTOR, "k8s-resource")


def _summary_evidence(evidence: list[Evidence]) -> list[Evidence]:
    return filter_evidence(evidence, _COLLECTOR, "k8s-manifest-summary")


def _has_dependency_annotation(annotations: dict[str, str] | None) -> list[str]:
    if not annotations:
        return []
    matched = []
    for key in annotations:
        for prefix in _DEPENDENCY_ANNOTATION_PREFIXES:
            if key.startswith(prefix) or key == prefix:
                matched.append(key)
                break
    return matched


class DependencyDeclarationRule:
    """PATCH-DEPS-001: detect dependency declaration annotations on workloads."""

    id = "PATCH-DEPS-001"
    band: Band = 2
    required_collectors: list[str] = [_COLLECTOR]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        summaries = _summary_evidence(evidence)
        if not summaries:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no k8s-manifest evidence available",
            )

        workloads = _workload_evidence(evidence)
        if not workloads:
            sm = summaries[0]
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_green_finding(
                        self.id,
                        "patch-deps-declaration",
                        sm,
                        summary=(
                            "No workload resources found"
                            " — dependency declaration check not applicable"
                        ),
                        confidence=0.80,
                        evidence_locator=".",
                    )
                ],
            )

        findings: list[Finding] = []
        for ev in workloads:
            name = ev.payload.get("name", "")
            annotations = ev.payload.get("annotations")
            matched = _has_dependency_annotation(annotations)

            if matched:
                findings.append(
                    make_green_finding(
                        self.id,
                        "patch-deps-declaration",
                        ev,
                        summary=(
                            f"Workload '{name}' declares dependencies"
                            f" via annotations: {', '.join(matched)}"
                        ),
                        recommendation=(
                            "No action required — dependency declarations are present."
                        ),
                        confidence=0.90,
                        evidence_locator=ev.locator,
                    )
                )
            else:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=f"Workload '{name}' has no dependency declaration annotations",
                        recommendation=(
                            "Add annotations such as app.kubernetes.io/part-of or "
                            "backstage.io/system to declare service dependencies "
                            "for patching blast-radius analysis."
                        ),
                        evidence_locator=ev.locator,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.85,
                        pattern_tag="patch-deps-declaration",
                    )
                )

        return RuleResult(rule_id=self.id, findings=findings)


class SharedFateIndicatorRule:
    """PATCH-DEPS-002: detect shared-fate indicators across workloads."""

    id = "PATCH-DEPS-002"
    band: Band = 1
    required_collectors: list[str] = [_COLLECTOR]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        summaries = _summary_evidence(evidence)
        if not summaries:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no k8s-manifest evidence available",
            )

        workloads = _workload_evidence(evidence)
        if not workloads:
            sm = summaries[0]
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_green_finding(
                        self.id,
                        "patch-deps-shared-fate",
                        sm,
                        summary=(
                            "No workload resources found — shared-fate check not applicable"
                        ),
                        confidence=0.80,
                        evidence_locator=".",
                    )
                ],
            )

        node_selector_groups: dict[str, list[tuple[str, Evidence]]] = defaultdict(list)
        db_host_groups: dict[str, list[tuple[str, Evidence]]] = defaultdict(list)

        for ev in workloads:
            name = ev.payload.get("name", "")
            ns = ev.payload.get("node_selector")
            if ns:
                key = str(sorted(ns.items()))
                node_selector_groups[key].append((name, ev))

            for container in ev.payload.get("containers") or []:
                for env_entry in container.get("env") or []:
                    env_name = env_entry.get("name", "")
                    env_value = env_entry.get("value") or ""
                    if env_name.upper() in _DB_HOST_PATTERNS and env_value:
                        db_host_groups[env_value].append((name, ev))

        findings: list[Finding] = []

        for _selector_key, members in node_selector_groups.items():
            if len(members) < 2:
                continue
            names = sorted({m[0] for m in members})
            ev0 = members[0][1]
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="amber",
                    severity="medium",
                    summary=(
                        f"Workloads share the same nodeSelector: "
                        f"{', '.join(names)} — patching the node pool affects all"
                    ),
                    recommendation=(
                        "Spread workloads across different node pools or "
                        "add pod anti-affinity to reduce shared-fate blast radius."
                    ),
                    evidence_locator=ev0.locator,
                    collector_name=ev0.collector_name,
                    collector_version=ev0.collector_version,
                    confidence=0.85,
                    pattern_tag="patch-deps-shared-fate",
                )
            )

        for db_host, members in db_host_groups.items():
            if len(members) < 2:
                continue
            names = sorted({m[0] for m in members})
            ev0 = members[0][1]
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="amber",
                    severity="medium",
                    summary=(
                        f"Workloads share the same database host '{db_host}': "
                        f"{', '.join(names)} — DB maintenance affects all"
                    ),
                    recommendation=(
                        "Document the shared database dependency and ensure "
                        "patching procedures account for the blast radius."
                    ),
                    evidence_locator=ev0.locator,
                    collector_name=ev0.collector_name,
                    collector_version=ev0.collector_version,
                    confidence=0.80,
                    pattern_tag="patch-deps-shared-fate",
                )
            )

        if not findings:
            sm = summaries[0]
            findings.append(
                make_green_finding(
                    self.id,
                    "patch-deps-shared-fate",
                    sm,
                    summary="No shared-fate indicators detected across workloads",
                    confidence=0.80,
                    evidence_locator=".",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _get_ring(labels: dict[str, str] | None) -> int | None:
    if not labels:
        return None
    for key in _RING_LABEL_KEYS:
        val = labels.get(key)
        if val is not None:
            try:
                return int(val)
            except (ValueError, TypeError):
                continue
    return None


def _extract_service_refs(containers: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    for container in containers:
        for env_entry in container.get("env") or []:
            value = env_entry.get("value") or ""
            if ".svc" in value or "." in value:
                parts = value.split("://")[-1].split(":")[0].split("/")[0]
                if "." in parts:
                    refs.append(parts.split(".")[0])
    return refs


class CrossRingDependencyRule:
    """PATCH-DEPS-003: detect cross-ring dependency direction violations."""

    id = "PATCH-DEPS-003"
    band: Band = 1
    required_collectors: list[str] = [_COLLECTOR]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        summaries = _summary_evidence(evidence)
        if not summaries:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no k8s-manifest evidence available",
            )

        workloads = _workload_evidence(evidence)
        if not workloads:
            sm = summaries[0]
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_green_finding(
                        self.id,
                        "patch-deps-cross-ring",
                        sm,
                        summary=(
                            "No workload resources found — cross-ring check not applicable"
                        ),
                        confidence=0.80,
                        evidence_locator=".",
                    )
                ],
            )

        ring_map: dict[str, int] = {}
        workload_map: dict[str, Evidence] = {}
        for ev in workloads:
            name = ev.payload.get("name", "")
            ring = _get_ring(ev.payload.get("labels"))
            if ring is not None:
                ring_map[name] = ring
                workload_map[name] = ev

        if not ring_map:
            sm = summaries[0]
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_green_finding(
                        self.id,
                        "patch-deps-cross-ring",
                        sm,
                        summary=(
                            "No ring labels found on workloads"
                            " — cross-ring dependency check not applicable"
                        ),
                        recommendation=(
                            "Consider adding ring labels (e.g. app.kubernetes.io/ring) "
                            "to workloads to enable patching dependency direction analysis."
                        ),
                        confidence=0.75,
                        evidence_locator=".",
                    )
                ],
            )

        findings: list[Finding] = []

        for ev in workloads:
            name = ev.payload.get("name", "")
            caller_ring = ring_map.get(name)
            if caller_ring is None:
                continue

            service_refs = _extract_service_refs(ev.payload.get("containers") or [])
            for ref_name in service_refs:
                target_ring = ring_map.get(ref_name)
                if target_ring is None:
                    continue
                if caller_ring > target_ring:
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="amber",
                            severity="high",
                            summary=(
                                f"Workload '{name}' (ring {caller_ring}) depends on "
                                f"'{ref_name}' (ring {target_ring}) — higher ring "
                                f"depends on lower ring"
                            ),
                            recommendation=(
                                "Reverse the dependency direction or move the target "
                                "service to a ring equal to or higher than the caller."
                            ),
                            evidence_locator=ev.locator,
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.80,
                            pattern_tag="patch-deps-cross-ring",
                        )
                    )

        if not findings:
            sm = summaries[0]
            findings.append(
                make_green_finding(
                    self.id,
                    "patch-deps-cross-ring",
                    sm,
                    summary=(
                        "Ring labels present and no cross-ring dependency violations detected"
                    ),
                    evidence_locator=".",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    for rule_cls in (
        DependencyDeclarationRule,
        SharedFateIndicatorRule,
        CrossRingDependencyRule,
    ):
        rule = rule_cls()
        if rule.id not in rule_registry:
            rule_registry.register(rule.id, rule)


_register()

__all__ = [
    "DependencyDeclarationRule",
    "SharedFateIndicatorRule",
    "CrossRingDependencyRule",
]
