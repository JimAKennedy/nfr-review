# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: helm-secret-leakage — flags plaintext secrets in Helm values
and rendered templates."""

from __future__ import annotations

import re
from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

_SECRET_KEY_RE = re.compile(
    r"(password|secret|token|api[_-]?key|apikey|private[_-]?key|credentials?)",
    re.IGNORECASE,
)

_FALSE_POSITIVE_VALUES = frozenset(
    {
        "",
        "CHANGEME",
        "changeme",
        "TODO",
        "todo",
        "null",
        "None",
        "none",
        "true",
        "false",
    }
)

_TEMPLATE_REF_RE = re.compile(r"\{\{.*?\}\}")


def _is_suspicious_value(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    if not stripped or stripped in _FALSE_POSITIVE_VALUES:
        return False
    if _TEMPLATE_REF_RE.search(stripped):
        return False
    return True


def _scan_dict_for_secrets(
    data: dict[str, Any],
    path_prefix: str = "",
) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    for key, value in data.items():
        full_path = f"{path_prefix}.{key}" if path_prefix else key
        if isinstance(value, dict):
            hits.extend(_scan_dict_for_secrets(value, full_path))
        elif _SECRET_KEY_RE.search(key) and _is_suspicious_value(value):
            hits.append((full_path, str(value)))
    return hits


class HelmSecretLeakageRule:
    """Flag plaintext secrets in Helm values.yaml and rendered manifests."""

    id = "helm-secret-leakage"
    band: Band = 1
    required_collectors: list[str] = ["helm"]
    required_tech: list[str] = ["helm"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        helm_evidence = filter_evidence(evidence, "helm", "helm-analysis")
        if not helm_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no helm-analysis evidence available",
            )

        findings: list[Finding] = []
        for ev in helm_evidence:
            chart_path = ev.payload.chart_path
            values = ev.payload.chart_values

            for key_path, val in _scan_dict_for_secrets(values):
                display_val = val[:20] + "..." if len(val) > 20 else val
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="red",
                        severity="high",
                        summary=(
                            f"Suspected plaintext secret at '{key_path}'"
                            f" in {chart_path}/values.yaml"
                            f" (value: '{display_val}')."
                        ),
                        recommendation=(
                            "Use Kubernetes Secrets, external secret"
                            " operators, or Helm's --set flag to inject"
                            " sensitive values at deploy time instead of"
                            " hardcoding them in values.yaml."
                        ),
                        evidence_locator=f"{chart_path}/values.yaml:{key_path}",
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.8,
                        pattern_tag="helm-secret-leakage",
                    )
                )

            for manifest in ev.payload.rendered_manifests:
                kind = manifest.get("kind", "")
                name = manifest.get("metadata", {}).get("name", "unknown")
                if kind == "Secret":
                    continue
                data_sections = []
                if isinstance(manifest.get("data"), dict):
                    data_sections.append(("data", manifest["data"]))
                if isinstance(manifest.get("spec"), dict):
                    data_sections.append(("spec", manifest["spec"]))

                for section_name, section_data in data_sections:
                    for key_path, _val in _scan_dict_for_secrets(section_data):
                        findings.append(
                            Finding(
                                rule_id=self.id,
                                rag="red",
                                severity="critical",
                                summary=(
                                    f"Suspected plaintext secret at"
                                    f" '{section_name}.{key_path}' in rendered"
                                    f" {kind}/{name} (not a K8s Secret resource)."
                                ),
                                recommendation=(
                                    "Move secrets into Kubernetes Secret"
                                    " resources and reference them via"
                                    " secretKeyRef in pod specs."
                                ),
                                evidence_locator=f"{chart_path}:{kind}/{name}",
                                collector_name=ev.collector_name,
                                collector_version=ev.collector_version,
                                confidence=0.7,
                                pattern_tag="helm-secret-leakage",
                            )
                        )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "helm-secret-leakage",
                    helm_evidence[0],
                    summary="No plaintext secrets detected in Helm charts.",
                    confidence=0.8,
                    evidence_locator="all-helm-charts",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "helm-secret-leakage" not in rule_registry:
        rule_registry.register("helm-secret-leakage", HelmSecretLeakageRule())


_register()

__all__ = ["HelmSecretLeakageRule"]
