# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: python-package-subdivision — detect god packages, flat structures,
and mixed concerns in Python projects using python-ast evidence.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.rules.framework import register
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

_GOD_PACKAGE_THRESHOLD = 15
_MIXED_CONCERN_GROUP_THRESHOLD = 3

# Regex to split PascalCase / camelCase class names into domain-like words.
_WORD_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\b)")

# Common infrastructure/utility words that do not indicate a domain concern.
_INFRA_WORDS = frozenset(
    {
        "base",
        "abstract",
        "mixin",
        "util",
        "utils",
        "helper",
        "helpers",
        "factory",
        "manager",
        "handler",
        "service",
        "controller",
        "config",
        "test",
        "tests",
        "mock",
        "stub",
        "error",
        "exception",
        "interface",
        "impl",
        "default",
        "common",
        "core",
        "internal",
        "dto",
        "enum",
        "type",
        "model",
        "schema",
        "info",
        "data",
        "context",
        "provider",
        "adapter",
        "converter",
        "mapper",
        "serializer",
        "deserializer",
        "validator",
        "builder",
        "registry",
        "listener",
        "event",
        "response",
        "request",
        "result",
    }
)


def _extract_domain_words(class_name: str) -> set[str]:
    """Extract domain-relevant words from a PascalCase/camelCase class name."""
    words = {w.lower() for w in _WORD_RE.findall(class_name)}
    return words - _INFRA_WORDS


def _package_from_module_path(module_path: str) -> str:
    """Extract the package from a dotted module path (all but last segment)."""
    parts = module_path.rsplit(".", 1)
    if len(parts) == 2:
        return parts[0]
    return module_path


@register
class PythonPackageSubdivisionRule:
    """Detect god packages, flat structures, and mixed concerns in Python."""

    id = "python-package-subdivision"
    band: Band = 2
    required_collectors: list[str] = ["python-ast"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        py_evidence = filter_evidence(evidence, "python-ast", "python-ast-file")
        if not py_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no python-ast evidence available",
            )

        # Group classes by package.
        package_classes: dict[str, list[str]] = defaultdict(list)
        for ev in py_evidence:
            module_path = ev.payload.module_path
            pkg = _package_from_module_path(module_path)
            for cls in ev.payload.classes:
                package_classes[pkg].append(cls.name)

        if not package_classes:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_green_finding(
                        self.id,
                        "python-pkg-subdivision-ok",
                        py_evidence[0],
                        summary="No Python classes found to analyse for package subdivision.",
                        confidence=0.80,
                    )
                ],
            )

        findings: list[Finding] = []
        ref_ev = py_evidence[0]

        # 1. God-package detection.
        for pkg, classes in sorted(package_classes.items()):
            if len(classes) > _GOD_PACKAGE_THRESHOLD:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="red",
                        severity="high",
                        summary=(
                            f"God package '{pkg}' contains {len(classes)} classes"
                            f" (threshold: {_GOD_PACKAGE_THRESHOLD})."
                        ),
                        recommendation=(
                            f"Decompose '{pkg}' into smaller sub-packages grouped"
                            " by domain concern. Large packages increase cognitive"
                            " load, slow navigation, and often hide mixed"
                            " responsibilities."
                        ),
                        evidence_locator="project-wide",
                        collector_name=ref_ev.collector_name,
                        collector_version=ref_ev.collector_version,
                        confidence=0.90,
                        pattern_tag="python-god-package",
                    )
                )

        # 2. Flat-structure detection (only 1 depth level).
        depths = set()
        for pkg in package_classes:
            depths.add(pkg.count(".") + 1)
        if len(package_classes) > 1 and max(depths) <= 1:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="amber",
                    severity="medium",
                    summary=(
                        "Flat package structure detected: all"
                        f" {len(package_classes)} packages are at depth 1."
                    ),
                    recommendation=(
                        "Consider introducing sub-packages to group related"
                        " modules by domain or layer (e.g. models, services,"
                        " api). Flat structures become unwieldy as the"
                        " project grows."
                    ),
                    evidence_locator="project-wide",
                    collector_name=ref_ev.collector_name,
                    collector_version=ref_ev.collector_version,
                    confidence=0.80,
                    pattern_tag="python-flat-structure",
                )
            )

        # 3. Mixed-concerns detection.
        for pkg, classes in sorted(package_classes.items()):
            domain_groups: set[str] = set()
            for cls_name in classes:
                domain_words = _extract_domain_words(cls_name)
                domain_groups.update(domain_words)
            if len(domain_groups) > _MIXED_CONCERN_GROUP_THRESHOLD:
                sample = sorted(domain_groups)[:5]
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=(
                            f"Package '{pkg}' has classes spanning"
                            f" {len(domain_groups)} domain concepts"
                            f" ({', '.join(sample)})."
                        ),
                        recommendation=(
                            f"Split '{pkg}' so each sub-package addresses a"
                            " single domain concern. Mixed concerns increase"
                            " coupling and make the package harder to reason"
                            " about."
                        ),
                        evidence_locator="project-wide",
                        collector_name=ref_ev.collector_name,
                        collector_version=ref_ev.collector_version,
                        confidence=0.75,
                        pattern_tag="python-mixed-concerns",
                    )
                )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "python-pkg-subdivision-ok",
                    ref_ev,
                    summary="Python package structure is well-subdivided.",
                    confidence=0.85,
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


__all__ = ["PythonPackageSubdivisionRule"]
