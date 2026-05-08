"""Rule: nodejs-sync-fs-api — detects sync FS calls blocking the loop."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry


class NodejsSyncFsApiRule:
    """Flag synchronous filesystem and child_process calls that block the event loop."""

    id = "nodejs-sync-fs-api"
    band: Band = 1
    required_collectors: list[str] = ["nodejs-ast"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        js_evidence = [
            e
            for e in evidence
            if e.collector_name == "nodejs-ast" and e.kind == "nodejs-ast-file"
        ]
        if not js_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no nodejs-ast evidence available",
            )

        findings: list[Finding] = []
        for ev in js_evidence:
            file_path = ev.payload.get("file_path", ev.locator)
            for call in ev.payload.get("sync_calls", []):
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=(
                            f"Synchronous call {call['method']}() at line {call['line']}"
                        ),
                        recommendation=(
                            "Use the async equivalent to avoid blocking the"
                            " event loop in production code."
                        ),
                        evidence_locator=f"{file_path}:{call['line']}",
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.9,
                        pattern_tag="nodejs-sync-fs-api",
                    )
                )

        if not findings:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary="No synchronous blocking calls detected.",
                    recommendation="No action required.",
                    evidence_locator="project-wide",
                    collector_name=js_evidence[0].collector_name,
                    collector_version=js_evidence[0].collector_version,
                    confidence=0.9,
                    pattern_tag="nodejs-sync-fs-api",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "nodejs-sync-fs-api" not in rule_registry:
        rule_registry.register("nodejs-sync-fs-api", NodejsSyncFsApiRule())


_register()

__all__ = ["NodejsSyncFsApiRule"]
