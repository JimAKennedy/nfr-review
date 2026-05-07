"""Rule: python-mutable-default — detects mutable default arguments in function definitions."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry

_MUTABLE_TYPES = frozenset({"list", "dict", "set"})


class PythonMutableDefaultRule:
    """Flag function definitions using mutable default arguments."""

    id = "python-mutable-default"
    band: Band = 1
    required_collectors: list[str] = ["python-ast"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        py_evidence = [
            e
            for e in evidence
            if e.collector_name == "python-ast" and e.kind == "python-ast-file"
        ]
        if not py_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no python-ast evidence available",
            )

        findings: list[Finding] = []
        for ev in py_evidence:
            file_path = ev.payload.get("file_path", ev.locator)
            for func in ev.payload.get("functions", []):
                for default in func.get("default_args", []):
                    if default["default_type"] in _MUTABLE_TYPES:
                        findings.append(
                            Finding(
                                rule_id=self.id,
                                rag="amber",
                                severity="medium",
                                summary=(
                                    f"Mutable default argument ({default['default_type']})"
                                    f" in {func['name']}() at line {default['line']}"
                                ),
                                recommendation=(
                                    "Use None as default and initialize in function body:"
                                    " if arg is None: arg = []"
                                ),
                                evidence_locator=f"{file_path}:{default['line']}",
                                collector_name=ev.collector_name,
                                collector_version=ev.collector_version,
                                confidence=0.9,
                                pattern_tag="mutable-default",
                            )
                        )

        if not findings:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary="No mutable default arguments detected.",
                    recommendation="No action required.",
                    evidence_locator="project-wide",
                    collector_name=py_evidence[0].collector_name,
                    collector_version=py_evidence[0].collector_version,
                    confidence=0.9,
                    pattern_tag="mutable-default",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "python-mutable-default" not in rule_registry:
        rule_registry.register("python-mutable-default", PythonMutableDefaultRule())


_register()

__all__ = ["PythonMutableDefaultRule"]
