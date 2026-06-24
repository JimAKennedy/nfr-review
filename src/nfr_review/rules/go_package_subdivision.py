# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: go-package-subdivision — detect god packages and mixed concerns
in Go projects using go-ast evidence.

Go packages are conventionally flatter than Java/Python, so the god-package
threshold is raised to 20 structs and the flat-structure check is skipped.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.rules.framework import register
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

_GOD_PACKAGE_THRESHOLD = 20
_MIXED_CONCERN_GROUP_THRESHOLD = 3

# Regex to split PascalCase / camelCase struct names into domain-like words.
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
        "opts",
        "options",
        "client",
        "server",
    }
)


def _extract_domain_words(struct_name: str) -> set[str]:
    """Extract domain-relevant words from a PascalCase struct name."""
    words = {w.lower() for w in _WORD_RE.findall(struct_name)}
    return words - _INFRA_WORDS


@register
class GoPackageSubdivisionRule:
    """Detect god packages and mixed concerns in Go projects."""

    id = "go-package-subdivision"
    band: Band = 2
    required_collectors: list[str] = ["go-ast"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        go_evidence = filter_evidence(evidence, "go-ast", "go-ast-file")
        if not go_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no go-ast evidence available",
            )

        # Group structs by package.
        package_structs: dict[str, list[str]] = defaultdict(list)
        for ev in go_evidence:
            pkg = ev.payload.package
            for struct in ev.payload.structs:
                package_structs[pkg].append(struct.name)

        if not package_structs:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_green_finding(
                        self.id,
                        "go-pkg-subdivision-ok",
                        go_evidence[0],
                        summary="No Go structs found to analyse for package subdivision.",
                        confidence=0.80,
                    )
                ],
            )

        findings: list[Finding] = []
        ref_ev = go_evidence[0]

        # 1. God-package detection (higher threshold for Go).
        for pkg, structs in sorted(package_structs.items()):
            if len(structs) > _GOD_PACKAGE_THRESHOLD:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="red",
                        severity="high",
                        summary=(
                            f"God package '{pkg}' contains {len(structs)} structs"
                            f" (threshold: {_GOD_PACKAGE_THRESHOLD})."
                        ),
                        recommendation=(
                            f"Decompose '{pkg}' into smaller packages grouped"
                            " by domain concern. Even in Go's flat package"
                            " convention, packages with many structs become"
                            " difficult to maintain and navigate."
                        ),
                        evidence_locator="project-wide",
                        collector_name=ref_ev.collector_name,
                        collector_version=ref_ev.collector_version,
                        confidence=0.90,
                        pattern_tag="go-god-package",
                    )
                )

        # 2. Mixed-concerns detection.
        for pkg, structs in sorted(package_structs.items()):
            domain_groups: set[str] = set()
            for struct_name in structs:
                domain_words = _extract_domain_words(struct_name)
                domain_groups.update(domain_words)
            if len(domain_groups) > _MIXED_CONCERN_GROUP_THRESHOLD:
                sample = sorted(domain_groups)[:5]
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=(
                            f"Package '{pkg}' has structs spanning"
                            f" {len(domain_groups)} domain concepts"
                            f" ({', '.join(sample)})."
                        ),
                        recommendation=(
                            f"Split '{pkg}' so each package addresses a"
                            " single domain concern. Go packages should be"
                            " small and focused with a clear purpose."
                        ),
                        evidence_locator="project-wide",
                        collector_name=ref_ev.collector_name,
                        collector_version=ref_ev.collector_version,
                        confidence=0.75,
                        pattern_tag="go-mixed-concerns",
                    )
                )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "go-pkg-subdivision-ok",
                    ref_ev,
                    summary="Go package structure is well-subdivided.",
                    confidence=0.85,
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


__all__ = ["GoPackageSubdivisionRule"]
