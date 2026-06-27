# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""HYG-LIC-003: License header presence in source files.

Checks source files for copyright/license headers using scancode copyright
evidence.  Amber for files missing headers; green when all checked files
have headers.  File extensions are configurable.
"""

from __future__ import annotations

from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.rules.rule_helpers import make_green_finding

_DEFAULT_EXTENSIONS = frozenset({".py", ".java", ".go", ".ts", ".js", ".rs"})
_SKIP_PREFIXES = (
    ".agents/",
    ".gsd/",
    "venv/",
    ".venv/",
    "node_modules/",
    "build/",
    "dist/",
    "out/",
)
_SKIP_SUFFIXES = (
    ".config.ts",
    ".config.js",
    ".config.mjs",
    ".config.cjs",
    ".generated.ts",
    ".generated.js",
    "conftest.py",
)


class LicenseHeaderRule:
    id = "HYG-LIC-003"
    band: Band = 1
    required_collectors: list[str] = ["license-scan"]
    category = "license"

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        per_file = [e for e in evidence if e.kind == "license-scan"]
        if not per_file:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no license-scan evidence available",
            )

        extensions = _DEFAULT_EXTENSIONS
        if context and hasattr(context, "extra"):
            cfg = getattr(context.extra, "license_headers", None)
            if cfg and isinstance(cfg, dict):
                ext_list = cfg.get("extensions")
                if ext_list and isinstance(ext_list, list):
                    extensions = frozenset(ext_list)

        relevant = [
            e
            for e in per_file
            if any(e.locator.endswith(ext) for ext in extensions)
            and not any(e.locator.startswith(p) for p in _SKIP_PREFIXES)
            and not any(e.locator.endswith(s) for s in _SKIP_SUFFIXES)
        ]

        if not relevant:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_green_finding(
                        self.id,
                        "license-header-presence",
                        summary="No source files in checked extensions found.",
                        collector_name="license-scan",
                        collector_version="0.1.0",
                        evidence_locator=".",
                        confidence=0.8,
                    )
                ],
            )

        missing: list[str] = []
        for ev in relevant:
            copyrights = ev.payload.copyrights
            licenses = ev.payload.licenses
            if not copyrights and not licenses:
                missing.append(ev.locator)

        findings: list[Finding] = []
        if missing:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="amber",
                    severity="medium",
                    summary=(
                        f"{len(missing)} source file(s) missing license/copyright "
                        f"headers: {', '.join(missing[:5])}"
                        + (" ..." if len(missing) > 5 else "")
                    ),
                    recommendation=(
                        "Add a license header (copyright notice + license identifier) "
                        "to the top of each source file."
                    ),
                    evidence_locator=missing[0],
                    collector_name="license-scan",
                    collector_version="0.1.0",
                    confidence=0.85,
                    pattern_tag="license-header-presence",
                )
            )
        else:
            findings.append(
                make_green_finding(
                    self.id,
                    "license-header-presence",
                    summary=(
                        f"All {len(relevant)} checked source file(s) "
                        "have license/copyright headers."
                    ),
                    collector_name="license-scan",
                    collector_version="0.1.0",
                    evidence_locator=".",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "HYG-LIC-003" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-LIC-003", LicenseHeaderRule())


_register()

__all__ = ["LicenseHeaderRule"]
