"""Rule: go-goroutine-leak — flags goroutine launches that may leak."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry


class GoGoroutineLeakRule:
    """Flag goroutine launches without explicit lifecycle management."""

    id = "go-goroutine-leak"
    band: Band = 1
    required_collectors: list[str] = ["go-ast"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        go_evidence = [
            e for e in evidence if e.collector_name == "go-ast" and e.kind == "go-ast-file"
        ]
        if not go_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no go-ast evidence available",
            )

        findings: list[Finding] = []
        for ev in go_evidence:
            file_path = ev.payload.get("file_path", ev.locator)
            for launch in ev.payload.get("goroutine_launches", []):
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=(
                            f"Goroutine launch at line {launch['line']}"
                            f" may leak without lifecycle management"
                        ),
                        recommendation=(
                            "Use context.Context, sync.WaitGroup, or errgroup"
                            " for goroutine lifecycle management."
                        ),
                        evidence_locator=f"{file_path}:{launch['line']}",
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.8,
                        pattern_tag="go-goroutine-leak",
                    )
                )

        if not findings:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary="No goroutine launches detected.",
                    recommendation="No action required.",
                    evidence_locator="project-wide",
                    collector_name=go_evidence[0].collector_name,
                    collector_version=go_evidence[0].collector_version,
                    confidence=0.8,
                    pattern_tag="go-goroutine-leak",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "go-goroutine-leak" not in rule_registry:
        rule_registry.register("go-goroutine-leak", GoGoroutineLeakRule())


_register()

__all__ = ["GoGoroutineLeakRule"]
