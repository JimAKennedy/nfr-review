"""Rule: logging-to-stdout — cross-language detection of stdout/stderr logging.

Uses D021 ANY-match semantics: required_collectors=[] and required_tech=[]
so the engine always runs it. The rule filters evidence internally.

Python: print(), sys.stdout.write(), sys.stderr.write()
Java:   System.out.println/print/printf(), System.err.println/print/printf()
"""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules._cross_language import ALL_LANGUAGES

_STDOUT_METHODS: dict[str, frozenset[str]] = {
    "python": frozenset({"print", "sys.stdout.write", "sys.stderr.write"}),
    "java": frozenset(
        {
            "System.out.println",
            "System.out.print",
            "System.out.printf",
            "System.err.println",
            "System.err.print",
            "System.err.printf",
        }
    ),
}


class LoggingToStdoutRule:
    """Flag direct stdout/stderr writes that should use a logging framework."""

    id = "logging-to-stdout"
    band: Band = 1
    required_collectors: list[str] = []
    required_tech: list[str] = []

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        findings: list[Finding] = []
        any_evidence = False
        first_ev: Evidence | None = None

        for lang in ALL_LANGUAGES:
            lang_ev = [
                e
                for e in evidence
                if e.collector_name == lang.collector_name and e.kind == lang.evidence_kind
            ]
            if not lang_ev:
                continue
            any_evidence = True
            if first_ev is None:
                first_ev = lang_ev[0]

            methods = _STDOUT_METHODS.get(lang.language, frozenset())

            for ev in lang_ev:
                file_path = ev.payload.get("file_path", ev.locator)
                for stmt in ev.payload.get("log_statements", []):
                    if stmt["method"] in methods:
                        findings.append(
                            Finding(
                                rule_id=self.id,
                                rag="amber",
                                severity="medium",
                                summary=(
                                    f"Logging to stdout via {stmt['method']}()"
                                    f" at line {stmt['line']}"
                                ),
                                recommendation=(
                                    "Use a structured logging framework instead of"
                                    " direct stdout/stderr writes."
                                ),
                                evidence_locator=f"{file_path}:{stmt['line']}",
                                collector_name=ev.collector_name,
                                collector_version=ev.collector_version,
                                confidence=0.85,
                                pattern_tag="logging-to-stdout",
                            )
                        )

        if not any_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no AST evidence available",
            )

        if not findings:
            assert first_ev is not None
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary="No stdout/stderr logging detected.",
                    recommendation="No action required.",
                    evidence_locator="project-wide",
                    collector_name=first_ev.collector_name,
                    collector_version=first_ev.collector_version,
                    confidence=0.85,
                    pattern_tag="logging-to-stdout",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "logging-to-stdout" not in rule_registry:
        rule_registry.register("logging-to-stdout", LoggingToStdoutRule())


_register()

__all__ = ["LoggingToStdoutRule"]
