# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""HYG-LIC-001: Copyleft license detection.

Flags GPL/AGPL/LGPL licenses found in source files or dependency evidence.
When the project's own root LICENSE/COPYING file is copyleft, findings from
the project's own source files are downgraded to green/info — the project
deliberately chose that license.
"""

from __future__ import annotations

from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.rules.rule_helpers import make_green_finding

_STRONG_COPYLEFT = frozenset({"gpl", "agpl"})
_WEAK_COPYLEFT = frozenset({"lgpl", "mpl"})

_LICENSE_INFRA_SUFFIXES = (
    "lic_copyleft.py",
    "lic_spdx.py",
    "lic_notice.py",
    "lic_headers.py",
    "license_scan.py",
)

_ROOT_LICENSE_NAMES = frozenset(
    {"LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE", "LICENCE.md", "COPYING"}
)


def _classify_license(spdx_key: str) -> str | None:
    lower = spdx_key.lower()
    if "agpl" in lower:
        return "agpl"
    if "lgpl" in lower:
        return "lgpl"
    if "gpl" in lower:
        return "gpl"
    if "mpl" in lower:
        return "mpl"
    return None


def detect_project_license_family(per_file: list[Evidence]) -> str | None:
    """Return the copyleft family of the project's root license, or None."""
    for ev in per_file:
        locator_upper = ev.locator.upper()
        if locator_upper not in {n.upper() for n in _ROOT_LICENSE_NAMES}:
            continue
        for lic in ev.payload.licenses:
            family = _classify_license(lic.get("spdx_key", ""))
            if family is not None:
                return family
    return None


class CopyleftDetectionRule:
    id = "HYG-LIC-001"
    band: Band = 1
    required_collectors: list[str] = ["license-scan"]
    category = "license"

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        per_file = [e for e in evidence if e.kind == "license-scan"]
        summary_ev = next(
            (e for e in evidence if e.kind == "license-scan-summary"),
            None,
        )

        if not per_file and summary_ev is None:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no license-scan evidence available",
            )

        project_family = detect_project_license_family(per_file)

        findings: list[Finding] = []
        seen: set[tuple[str, str]] = set()

        for ev in per_file:
            if any(ev.locator.endswith(s) for s in _LICENSE_INFRA_SUFFIXES):
                continue

            licenses = ev.payload.licenses
            for lic in licenses:
                spdx = lic.get("spdx_key", "")
                family = _classify_license(spdx)
                if family is None:
                    continue

                dedup_key = (ev.locator, spdx)
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                if project_family and family == project_family:
                    findings.append(
                        make_green_finding(
                            self.id,
                            "copyleft-detection",
                            ev,
                            summary=(
                                f"Project license is {spdx} — consistent with "
                                f"project's own {project_family.upper()} license."
                            ),
                            evidence_locator=ev.locator,
                            confidence=0.95,
                        )
                    )
                    continue

                if family in _STRONG_COPYLEFT:
                    summary = (
                        f"Copyleft license {spdx} detected in {ev.locator}. "
                        "Incompatible with permissive release."
                    )
                    recommendation = (
                        "Remove or replace this file/dependency, or obtain "
                        "a license exception from the copyright holder."
                    )
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="red",
                            severity="high",
                            summary=summary,
                            recommendation=recommendation,
                            evidence_locator=ev.locator,
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.9,
                            pattern_tag="copyleft-detection",
                        )
                    )
                else:
                    summary = (
                        f"Weak copyleft license {spdx} detected in "
                        f"{ev.locator}. Dynamic linking is typically acceptable."
                    )
                    recommendation = (
                        "Verify that usage is limited to dynamic linking. "
                        "Consult legal if embedding or modifying."
                    )
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="amber",
                            severity="medium",
                            summary=summary,
                            recommendation=recommendation,
                            evidence_locator=ev.locator,
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.9,
                            pattern_tag="copyleft-detection",
                        )
                    )

        if not findings:
            if summary_ev:
                findings.append(
                    make_green_finding(
                        self.id,
                        "copyleft-detection",
                        summary_ev,
                        summary="No copyleft licenses detected in scanned files.",
                        evidence_locator=".",
                        confidence=0.9,
                    )
                )
            else:
                findings.append(
                    make_green_finding(
                        self.id,
                        "copyleft-detection",
                        summary="No copyleft licenses detected in scanned files.",
                        collector_name="license-scan",
                        collector_version="0.1.0",
                        evidence_locator=".",
                        confidence=0.9,
                    )
                )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "HYG-LIC-001" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-LIC-001", CopyleftDetectionRule())


_register()

__all__ = ["CopyleftDetectionRule"]
