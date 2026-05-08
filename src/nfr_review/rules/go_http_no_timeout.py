"""Rule: go-http-no-timeout — detects HTTP calls without explicit timeouts."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry

_DEFAULT_CLIENT_CALLS = frozenset({"http.Get", "http.Post", "http.Head", "http.PostForm"})


class GoHttpNoTimeoutRule:
    """Flag HTTP calls using DefaultClient or Client without Timeout."""

    id = "go-http-no-timeout"
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
            for call in ev.payload.get("http_calls", []):
                call_name = call["call"]
                if call_name in _DEFAULT_CLIENT_CALLS:
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="red",
                            severity="high",
                            summary=(
                                f"{call_name}() uses DefaultClient with no timeout"
                                f" at line {call['line']}"
                            ),
                            recommendation=(
                                "Use an http.Client with an explicit Timeout"
                                " instead of the package-level convenience functions."
                            ),
                            evidence_locator=f"{file_path}:{call['line']}",
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.95,
                            pattern_tag="go-http-no-timeout",
                        )
                    )
                elif call_name == "http.Client" and not call["has_timeout"]:
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="amber",
                            severity="medium",
                            summary=(f"http.Client without Timeout at line {call['line']}"),
                            recommendation=(
                                "Set an explicit Timeout on the http.Client"
                                " to prevent indefinite hangs."
                            ),
                            evidence_locator=f"{file_path}:{call['line']}",
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.9,
                            pattern_tag="go-http-no-timeout",
                        )
                    )

        if not findings:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary="No HTTP calls without timeouts detected.",
                    recommendation="No action required.",
                    evidence_locator="project-wide",
                    collector_name=go_evidence[0].collector_name,
                    collector_version=go_evidence[0].collector_version,
                    confidence=0.9,
                    pattern_tag="go-http-no-timeout",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "go-http-no-timeout" not in rule_registry:
        rule_registry.register("go-http-no-timeout", GoHttpNoTimeoutRule())


_register()

__all__ = ["GoHttpNoTimeoutRule"]
