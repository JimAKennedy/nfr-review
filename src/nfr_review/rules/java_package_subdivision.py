# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: java-package-subdivision — detect god packages, flat structures,
and mixed concerns in Java projects using java-ast evidence.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from nfr_review.collectors.payloads.java_ast import JavaAstFilePayload
from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.rules.framework import FieldRule, Hit, make_finding
from nfr_review.rules.rule_helpers import make_green_finding

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


class JavaPackageSubdivisionRule(FieldRule[JavaAstFilePayload]):
    """Detect god packages, flat structures, and mixed concerns in Java."""

    id = "java-package-subdivision"
    band = 2
    collector_name = "java-ast"
    evidence_kind = "java-ast-file"
    payload_type = JavaAstFilePayload
    pattern_tag = "java-god-package"
    default_confidence = 0.85
    all_clear_summary = "Java package structure is well-subdivided."

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        relevant = [
            e
            for e in evidence
            if e.collector_name == self.collector_name and e.kind == self.evidence_kind
        ]
        if not relevant:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no java-ast evidence available",
            )

        # Group classes by package.
        package_classes: dict[str, list[str]] = defaultdict(list)
        for ev in relevant:
            payload = self._coerce(ev.payload)
            pkg = payload.package
            for cls in payload.classes:
                package_classes[pkg].append(cls.name)

        if not package_classes:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_green_finding(
                        self.id,
                        "java-pkg-subdivision-ok",
                        relevant[0],
                        summary="No Java classes found to analyse for package subdivision.",
                        confidence=0.80,
                    )
                ],
            )

        findings: list[Finding] = []
        ref_ev = relevant[0]

        # 1. God-package detection.
        for pkg, classes in sorted(package_classes.items()):
            if len(classes) > _GOD_PACKAGE_THRESHOLD:
                findings.append(
                    make_finding(
                        rule_id=self.id,
                        hit=Hit(
                            rag="red",
                            severity="high",
                            summary=(
                                f"God package '{pkg}' contains {len(classes)} classes"
                                f" (threshold: {_GOD_PACKAGE_THRESHOLD})."
                            ),
                            recommendation=(
                                f"Decompose '{pkg}' into smaller sub-packages grouped"
                                " by domain concern. Large Java packages increase"
                                " cognitive load, slow IDE navigation, and often hide"
                                " mixed responsibilities."
                            ),
                            locator="project-wide",
                        ),
                        ev=ref_ev,
                        pattern_tag="java-god-package",
                        default_confidence=0.90,
                    )
                )

        # 2. Flat-structure detection (only 1 depth level).
        depths = set()
        for pkg in package_classes:
            depths.add(pkg.count(".") + 1)
        if len(package_classes) > 1 and max(depths) <= 1:
            findings.append(
                make_finding(
                    rule_id=self.id,
                    hit=Hit(
                        rag="amber",
                        severity="medium",
                        summary=(
                            "Flat package structure detected: all"
                            f" {len(package_classes)} packages are at depth 1."
                        ),
                        recommendation=(
                            "Consider introducing sub-packages to group related"
                            " classes by domain or layer (e.g. com.example.order,"
                            " com.example.payment). Flat Java packages become"
                            " unwieldy as the project grows."
                        ),
                        locator="project-wide",
                    ),
                    ev=ref_ev,
                    pattern_tag="java-flat-structure",
                    default_confidence=0.80,
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
                    make_finding(
                        rule_id=self.id,
                        hit=Hit(
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
                            locator="project-wide",
                        ),
                        ev=ref_ev,
                        pattern_tag="java-mixed-concerns",
                        default_confidence=0.75,
                    )
                )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "java-pkg-subdivision-ok",
                    ref_ev,
                    summary="Java package structure is well-subdivided.",
                    confidence=0.85,
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


__all__ = ["JavaPackageSubdivisionRule"]
