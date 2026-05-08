"""Rule: csharp-async-void — detects async void methods in C# code."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry


class CSharpAsyncVoidRule:
    """Flag async void methods that should be async Task."""

    id = "csharp-async-void"
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
            for method in ev.payload.get("methods", []):
                if method["is_async"] and method["return_type"] == "void":
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="red",
                            severity="high",
                            summary=(
                                f"async void method '{method['name']}'"
                                f" at line {method['line']}"
                            ),
                            recommendation=(
                                "Change return type to async Task. async void"
                                " silently swallows exceptions and cannot be awaited."
                            ),
                            evidence_locator=f"{file_path}:{method['line']}",
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.95,
                            pattern_tag="csharp-async-void",
                        )
                    )

        if not findings:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary="No async void methods detected.",
                    recommendation="No action required.",
                    evidence_locator="project-wide",
                    collector_name=cs_evidence[0].collector_name,
                    collector_version=cs_evidence[0].collector_version,
                    confidence=0.9,
                    pattern_tag="csharp-async-void",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "csharp-async-void" not in rule_registry:
        rule_registry.register("csharp-async-void", CSharpAsyncVoidRule())


_register()

__all__ = ["CSharpAsyncVoidRule"]
