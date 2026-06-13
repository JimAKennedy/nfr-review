# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""PATCH-SCOPE rules — patch class scoping configuration detection.

PATCH-SCOPE-001: Patch class soak configuration detection.
    GREEN  if files matching patch-class config naming conventions are found,
           or parsed patch-config evidence confirms soak structure.
    AMBER  if parsed config exists but contains no patch class definitions.
    INFO   if no patch-class config files detected.
    SKIPPED when no repo-structure-summary evidence available.

PATCH-SCOPE-002: Accelerated cadence declaration.
    GREEN  if critical-security patch class has explicit compressed non-zero soak.
    AMBER  if patch config exists but no accelerated cadence for critical-security.
    INFO   if no patch-class config files detected.
    SKIPPED when no repo-structure-summary evidence available.
"""

from __future__ import annotations

import re
from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

_PATCH_CONFIG_FILE_PATTERNS = [
    re.compile(r"^patch[-_]?config", re.IGNORECASE),
    re.compile(r"^patching[-_]?policy", re.IGNORECASE),
    re.compile(r"^soak[-_]?config", re.IGNORECASE),
    re.compile(r"^patch[-_]?class", re.IGNORECASE),
    re.compile(r"^patching[-_]?config", re.IGNORECASE),
]

_PATCH_CONFIG_DIR_PATTERNS = [
    re.compile(r"^patch[-_]?config$", re.IGNORECASE),
    re.compile(r"^patching[-_]?policy$", re.IGNORECASE),
    re.compile(r"^soak[-_]?config$", re.IGNORECASE),
    re.compile(r"^patching$", re.IGNORECASE),
]

_CRITICAL_SECURITY_NAMES = frozenset(
    {
        "critical-security",
        "critical_security",
        "critical-sec",
        "critical",
    }
)


def _repo_summary_evidence(evidence: list[Evidence]) -> list[Evidence]:
    return filter_evidence(evidence, "repo-structure", "repo-structure-summary")


def _patch_config_evidence(evidence: list[Evidence]) -> list[Evidence]:
    return [e for e in evidence if e.kind == "patch-config"]


def _matches_file_pattern(name: str) -> bool:
    return any(p.search(name) for p in _PATCH_CONFIG_FILE_PATTERNS)


def _matches_dir_pattern(name: str) -> bool:
    return any(p.search(name) for p in _PATCH_CONFIG_DIR_PATTERNS)


def _find_config_files(ev: Evidence) -> list[str]:
    top_files: list[str] = ev.payload.get("top_level_files", [])
    top_dirs: list[str] = ev.payload.get("top_level_dirs", [])
    matched = [f for f in top_files if _matches_file_pattern(f)]
    matched += [d for d in top_dirs if _matches_dir_pattern(d)]
    return matched


class PatchClassSoakConfigRule:
    """PATCH-SCOPE-001: detect patch class soak configuration."""

    id = "PATCH-SCOPE-001"
    band: Band = 2
    required_collectors: list[str] = ["repo-structure"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        summaries = _repo_summary_evidence(evidence)
        if not summaries:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no repo-structure-summary evidence available",
            )

        parsed = _patch_config_evidence(evidence)
        if parsed:
            return self._evaluate_parsed(parsed)

        sm = summaries[0]
        matched = _find_config_files(sm)

        if matched:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_green_finding(
                        self.id,
                        "patch-scope-soak-config",
                        sm,
                        summary=f"Patch class config file(s) detected: {', '.join(matched)}",
                        recommendation=(
                            "No action required — patch class configuration files are present."
                        ),
                        confidence=0.80,
                        evidence_locator="repo-root",
                    )
                ],
            )

        return RuleResult(
            rule_id=self.id,
            findings=[
                make_green_finding(
                    self.id,
                    "patch-scope-soak-config",
                    sm,
                    summary="No patch-class soak configuration files detected",
                    recommendation=(
                        "If this service participates in a ringed patching programme,"
                        " add a patch-config or patching-policy file declaring"
                        " per-class soak durations."
                    ),
                    confidence=0.75,
                    evidence_locator="repo-root",
                )
            ],
        )

    def _evaluate_parsed(self, parsed: list[Evidence]) -> RuleResult:
        findings: list[Finding] = []
        for ev in parsed:
            file_path = ev.payload.get("file_path", ev.locator)
            patch_classes = ev.payload.get("patch_classes", [])
            if patch_classes:
                findings.append(
                    make_green_finding(
                        self.id,
                        "patch-scope-soak-config",
                        ev,
                        summary=(
                            f"Patch class soak configuration found in {file_path}"
                            f" with {len(patch_classes)} patch class(es) defined"
                        ),
                        recommendation=(
                            "No action required — patch class soak configuration is present."
                        ),
                        confidence=0.95,
                        evidence_locator=ev.locator,
                    )
                )
            else:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=(
                            f"Patch config file {file_path} found"
                            " but contains no patch class definitions"
                        ),
                        recommendation=(
                            "Add patch class definitions with soak durations"
                            " per ring to the configuration file."
                        ),
                        evidence_locator=ev.locator,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.85,
                        pattern_tag="patch-scope-soak-config",
                    )
                )
        return RuleResult(rule_id=self.id, findings=findings)


class AcceleratedCadenceRule:
    """PATCH-SCOPE-002: detect accelerated cadence for critical-security patches."""

    id = "PATCH-SCOPE-002"
    band: Band = 2
    required_collectors: list[str] = ["repo-structure"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        summaries = _repo_summary_evidence(evidence)
        if not summaries:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no repo-structure-summary evidence available",
            )

        parsed = _patch_config_evidence(evidence)
        if parsed:
            result = self._evaluate_parsed(parsed)
            if result is not None:
                return result

        sm = summaries[0]
        matched = _find_config_files(sm)

        if matched and not parsed:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_green_finding(
                        self.id,
                        "patch-scope-accelerated",
                        sm,
                        summary=(
                            "Patch config files detected but content not parsed"
                            " — cannot verify accelerated cadence declaration"
                        ),
                        recommendation=(
                            "Ensure the patch config includes a critical-security"
                            " class with compressed but non-zero soak times."
                        ),
                        confidence=0.60,
                        evidence_locator="repo-root",
                    )
                ],
            )

        return RuleResult(
            rule_id=self.id,
            findings=[
                make_green_finding(
                    self.id,
                    "patch-scope-accelerated",
                    sm,
                    summary=(
                        "No patch-class configuration detected"
                        " — accelerated cadence check not applicable"
                    ),
                    recommendation=(
                        "If this service participates in a ringed patching programme,"
                        " add a patching-policy or patch-config file with explicit"
                        " handling for critical-security patches."
                    ),
                    confidence=0.75,
                    evidence_locator="repo-root",
                )
            ],
        )

    def _evaluate_parsed(self, parsed: list[Evidence]) -> RuleResult | None:
        findings: list[Finding] = []
        has_any_classes = False
        found_critical = False

        for ev in parsed:
            file_path = ev.payload.get("file_path", ev.locator)
            patch_classes = ev.payload.get("patch_classes", [])
            if not patch_classes:
                continue
            has_any_classes = True

            for pc in patch_classes:
                name = pc.get("name", "").lower().strip()
                if name not in _CRITICAL_SECURITY_NAMES:
                    continue

                soak_hours = pc.get("soak_hours")
                if not soak_hours:
                    continue

                values: list[int | float] = []
                if isinstance(soak_hours, dict):
                    values = [v for v in soak_hours.values() if isinstance(v, (int, float))]
                elif isinstance(soak_hours, list):
                    values = [v for v in soak_hours if isinstance(v, (int, float))]

                if values and all(v > 0 for v in values):
                    found_critical = True
                    findings.append(
                        make_green_finding(
                            self.id,
                            "patch-scope-accelerated",
                            ev,
                            summary=(
                                f"Critical-security patch class in {file_path}"
                                f" declares accelerated cadence with non-zero"
                                f" soak times"
                            ),
                            recommendation=(
                                "No action required — accelerated cadence"
                                " for critical-security patches is declared."
                            ),
                            confidence=0.95,
                            evidence_locator=ev.locator,
                        )
                    )

        if has_any_classes and not found_critical:
            ev0 = parsed[0]
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="amber",
                    severity="medium",
                    summary=(
                        "Patch config exists but no accelerated cadence"
                        " declared for critical-security patch class"
                    ),
                    recommendation=(
                        "Add a critical-security patch class with compressed"
                        " but non-zero soak times to handle urgent security"
                        " patches (CVSS >= 9, KEV-listed) without bypassing"
                        " ring guardrails."
                    ),
                    evidence_locator=ev0.locator,
                    collector_name=ev0.collector_name,
                    collector_version=ev0.collector_version,
                    confidence=0.85,
                    pattern_tag="patch-scope-accelerated",
                )
            )

        if findings:
            return RuleResult(rule_id=self.id, findings=findings)
        return None


def _register() -> None:
    for rule_cls in (PatchClassSoakConfigRule, AcceleratedCadenceRule):
        rule = rule_cls()
        if rule.id not in rule_registry:
            rule_registry.register(rule.id, rule)


_register()

__all__ = ["PatchClassSoakConfigRule", "AcceleratedCadenceRule"]
