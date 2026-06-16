# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""HYG-BLD-005: Code debt marker threshold check."""

from __future__ import annotations

from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.rules.rule_helpers import make_green_finding

_DEFAULT_THRESHOLD = 20


class CodeDebtRule:
    id = "HYG-BLD-005"
    band: Band = 1
    required_collectors: list[str] = ["code-debt"]
    category = "build-readiness"

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        ev = next((e for e in evidence if e.kind == "code-debt-analysis"), None)
        if ev is None:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no code-debt-analysis evidence available",
            )

        total = ev.payload.total_markers
        per_marker = ev.payload.per_marker
        top_files = ev.payload.top_files
        file_count = ev.payload.file_count

        threshold = _DEFAULT_THRESHOLD

        if total == 0:
            finding = make_green_finding(
                self.id,
                "code-debt",
                ev,
                summary="No code debt markers (TODO/FIXME/HACK) found.",
                evidence_locator=ev.locator,
                confidence=1.0,
            )
        elif total <= threshold:
            marker_summary = ", ".join(
                f"{k}: {v}" for k, v in sorted(per_marker.items()) if v > 0
            )
            finding = make_green_finding(
                self.id,
                "code-debt",
                ev,
                summary=(
                    f"{total} code debt marker(s) in {file_count} file(s) "
                    f"(within threshold of {threshold}). {marker_summary}."
                ),
                evidence_locator=ev.locator,
                confidence=1.0,
            )
        else:
            marker_summary = ", ".join(
                f"{k}: {v}" for k, v in sorted(per_marker.items()) if v > 0
            )
            top_file_list = ", ".join(f"{f['path']} ({f['count']})" for f in top_files[:5])
            finding = Finding(
                rule_id=self.id,
                rag="amber",
                severity="low",
                summary=(
                    f"{total} code debt markers across {file_count} file(s) "
                    f"exceeds threshold of {threshold}. {marker_summary}."
                ),
                recommendation=(
                    f"Review and address debt markers, starting with: {top_file_list}."
                ),
                evidence_locator=ev.locator,
                collector_name=ev.collector_name,
                collector_version=ev.collector_version,
                confidence=0.9,
                pattern_tag="code-debt",
            )

        return RuleResult(rule_id=self.id, findings=[finding])


def _register() -> None:
    if "HYG-BLD-005" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-BLD-005", CodeDebtRule())


_register()

__all__ = ["CodeDebtRule"]
