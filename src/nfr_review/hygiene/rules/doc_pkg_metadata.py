"""HYG-DOC-001: Package metadata completeness check."""

from __future__ import annotations

from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import RAG, Evidence, Finding, RuleResult, Severity
from nfr_review.protocols import Band

_KEY_FIELDS = ("description", "license", "urls", "homepage")


class PkgMetadataRule:
    id = "HYG-DOC-001"
    band: Band = 1
    required_collectors: list[str] = ["documentation"]
    category = "documentation"

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        ev = next((e for e in evidence if e.kind == "documentation-analysis"), None)
        if ev is None:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no documentation-analysis evidence available",
            )

        manifests: list[dict[str, Any]] = ev.payload.get("manifests", [])

        if not manifests:
            finding = Finding(
                rule_id=self.id,
                rag="red",
                severity="high",
                summary="No package manifest found (pyproject.toml, package.json).",
                recommendation="Add a pyproject.toml or package.json with project metadata.",
                evidence_locator=ev.locator,
                collector_name=ev.collector_name,
                collector_version=ev.collector_version,
                confidence=1.0,
                pattern_tag="pkg-metadata-missing",
            )
            return RuleResult(rule_id=self.id, findings=[finding])

        findings: list[Finding] = []

        for manifest in manifests:
            missing = manifest.get("fields_missing", [])
            key_missing = [f for f in missing if f in _KEY_FIELDS]

            if len(key_missing) > 2:
                rag: RAG = "amber"
                severity: Severity = "medium"
                summary = (
                    f"{manifest['path']}: missing {len(key_missing)} key fields "
                    f"({', '.join(key_missing)})."
                )
                recommendation = f"Add missing fields to {manifest['path']}."
            elif key_missing:
                rag = "green"
                severity = "info"
                summary = (
                    f"{manifest['path']}: {len(key_missing)} non-critical field(s) missing "
                    f"({', '.join(key_missing)})."
                )
                recommendation = "No urgent action required."
            else:
                rag = "green"
                severity = "info"
                summary = f"{manifest['path']}: all key metadata fields present."
                recommendation = "No action required."

            findings.append(
                Finding(
                    rule_id=self.id,
                    rag=rag,
                    severity=severity,
                    summary=summary,
                    recommendation=recommendation,
                    evidence_locator=manifest.get("path", ev.locator),
                    collector_name=ev.collector_name,
                    collector_version=ev.collector_version,
                    confidence=1.0,
                    pattern_tag="pkg-metadata-completeness",
                )
            )

        if not findings:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary="Package metadata present.",
                    recommendation="No action required.",
                    evidence_locator=ev.locator,
                    collector_name=ev.collector_name,
                    collector_version=ev.collector_version,
                    confidence=1.0,
                    pattern_tag="pkg-metadata-completeness",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "HYG-DOC-001" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-DOC-001", PkgMetadataRule())


_register()

__all__ = ["PkgMetadataRule"]
