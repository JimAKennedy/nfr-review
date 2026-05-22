# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: csharp-disposable-no-using — detects IDisposable creation without using statement."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry

_DISPOSABLE_TYPES = frozenset(
    {
        "FileStream",
        "StreamReader",
        "StreamWriter",
        "SqlConnection",
        "SqlCommand",
        "HttpClient",
        "MemoryStream",
        "BinaryReader",
        "BinaryWriter",
        "TcpClient",
        "NetworkStream",
    }
)


class CSharpDisposableNoUsingRule:
    """Flag IDisposable object creation not wrapped in a using statement."""

    id = "csharp-disposable-no-using"
    band: Band = 1
    required_collectors: list[str] = ["csharp-ast"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        cs_evidence = [
            e
            for e in evidence
            if e.collector_name == "csharp-ast" and e.kind == "csharp-ast-file"
        ]
        if not cs_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no csharp-ast evidence available",
            )

        findings: list[Finding] = []
        for ev in cs_evidence:
            file_path = ev.payload.get("file_path", ev.locator)
            for creation in ev.payload.get("object_creations", []):
                if creation["type_name"] in _DISPOSABLE_TYPES and not creation["in_using"]:
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="amber",
                            severity="medium",
                            summary=f"{creation['type_name']} created without using statement",
                            recommendation=(
                                "Wrap IDisposable objects in a using statement or"
                                " using declaration to ensure proper resource cleanup."
                            ),
                            evidence_locator=f"{file_path}:{creation['line']}",
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.85,
                            pattern_tag="csharp-disposable-no-using",
                        )
                    )

        if not findings:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary="All IDisposable objects properly wrapped in using.",
                    recommendation="No action required.",
                    evidence_locator="project-wide",
                    collector_name=cs_evidence[0].collector_name,
                    collector_version=cs_evidence[0].collector_version,
                    confidence=0.85,
                    pattern_tag="csharp-disposable-no-using",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "csharp-disposable-no-using" not in rule_registry:
        rule_registry.register("csharp-disposable-no-using", CSharpDisposableNoUsingRule())


_register()

__all__ = ["CSharpDisposableNoUsingRule"]
