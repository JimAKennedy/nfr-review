# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: helm-secret-leakage — flags plaintext secrets in Helm values
and rendered templates."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from nfr_review.collectors.payloads.helm import HelmAnalysisPayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit

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


class HelmSecretLeakageRule(FieldRule[HelmAnalysisPayload]):
    """Flag plaintext secrets in Helm values.yaml and rendered manifests."""

    id = "helm-secret-leakage"
    collector_name = "helm"
    evidence_kind = "helm-analysis"
    payload_type = HelmAnalysisPayload
    pattern_tag = "helm-secret-leakage"
    required_tech = ["helm"]
    default_confidence = 0.8
    all_clear_summary = "No plaintext secrets detected in Helm charts."
    all_clear_recommendation = "No action required."

    def check(self, payload: HelmAnalysisPayload, ev: Evidence) -> Iterable[Hit]:
        chart_path = payload.chart_path
        values = payload.chart_values

        for key_path, val in _scan_dict_for_secrets(values):
            display_val = val[:20] + "..." if len(val) > 20 else val
            yield Hit(
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
                locator=f"{chart_path}/values.yaml:{key_path}",
            )

        for manifest in payload.rendered_manifests:
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
                    yield Hit(
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
                        locator=f"{chart_path}:{kind}/{name}",
                        confidence=0.7,
                    )


__all__ = ["HelmSecretLeakageRule"]
