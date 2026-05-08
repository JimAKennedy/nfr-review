"""Rule: csharp-configure-await — detects await expressions missing ConfigureAwait(false)."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry


class CSharpConfigureAwaitRule:
    """Flag await expressions that lack ConfigureAwait(false) in library code."""

    id = "csharp-configure-await"
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
            for await_expr in ev.payload.get("await_expressions", []):
                if not await_expr["has_configure_await"]:
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="amber",
                            severity="medium",
                            summary=(
                                f"await without ConfigureAwait(false)"
                                f" at line {await_expr['line']}"
                            ),
                            recommendation=(
                                "Add .ConfigureAwait(false) to avoid capturing the"
                                " synchronization context in library code."
                            ),
                            evidence_locator=f"{file_path}:{await_expr['line']}",
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.8,
                            pattern_tag="csharp-configure-await",
                        )
                    )

        if not findings:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary="All await expressions use ConfigureAwait.",
                    recommendation="No action required.",
                    evidence_locator="project-wide",
                    collector_name=cs_evidence[0].collector_name,
                    collector_version=cs_evidence[0].collector_version,
                    confidence=0.85,
                    pattern_tag="csharp-configure-await",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "csharp-configure-await" not in rule_registry:
        rule_registry.register("csharp-configure-await", CSharpConfigureAwaitRule())


_register()

__all__ = ["CSharpConfigureAwaitRule"]
