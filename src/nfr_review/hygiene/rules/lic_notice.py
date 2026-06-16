# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""HYG-LIC-002: NOTICE file completeness.

Cross-references third-party copyright holders from license-scan evidence
against entries in the repo's NOTICE file.  Red if NOTICE is absent when
third-party copyrights exist; amber for missing entries; green when complete.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.rules.rule_helpers import make_green_finding

logger = logging.getLogger(__name__)

_SPDX_JUNK = re.compile(r"\s*SPDX-License-Identifier.*", re.IGNORECASE)


class NoticeCompletenessRule:
    id = "HYG-LIC-002"
    band: Band = 1
    required_collectors: list[str] = ["license-scan"]
    category = "license"

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        summary_ev = next(
            (e for e in evidence if e.kind == "license-scan-summary"),
            None,
        )
        if summary_ev is None:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no license-scan-summary evidence available",
            )

        per_file = [e for e in evidence if e.kind == "license-scan"]
        all_holders: set[str] = set()
        for ev in per_file:
            for h in ev.payload.holders:
                if h and h.strip():
                    cleaned = _SPDX_JUNK.sub("", h).strip()
                    if cleaned:
                        all_holders.add(cleaned)

        if not all_holders:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_green_finding(
                        self.id,
                        "notice-completeness",
                        summary_ev,
                        summary="No third-party copyright holders detected.",
                        evidence_locator=".",
                        confidence=0.8,
                    )
                ],
            )

        repo_path = self._resolve_repo_path(context)
        notice_text = self._read_notice(repo_path)

        if notice_text is None:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    Finding(
                        rule_id=self.id,
                        rag="red",
                        severity="high",
                        summary=(
                            "NOTICE file is missing but third-party copyrights "
                            f"detected ({len(all_holders)} holder(s))."
                        ),
                        recommendation=(
                            "Create a NOTICE file listing all third-party "
                            "copyright holders and their license terms."
                        ),
                        evidence_locator="NOTICE",
                        collector_name=summary_ev.collector_name,
                        collector_version=summary_ev.collector_version,
                        confidence=0.85,
                        pattern_tag="notice-completeness",
                    )
                ],
            )

        notice_lower = notice_text.lower()
        missing = [h for h in sorted(all_holders) if h.lower() not in notice_lower]

        if missing:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=(
                            f"NOTICE file is missing {len(missing)} "
                            f"attribution(s): {', '.join(missing[:5])}"
                            + (" ..." if len(missing) > 5 else "")
                        ),
                        recommendation=(
                            "Update the NOTICE file to include all third-party "
                            "copyright holders detected in the repository."
                        ),
                        evidence_locator="NOTICE",
                        collector_name=summary_ev.collector_name,
                        collector_version=summary_ev.collector_version,
                        confidence=0.8,
                        pattern_tag="notice-completeness",
                    )
                ],
            )

        return RuleResult(
            rule_id=self.id,
            findings=[
                make_green_finding(
                    self.id,
                    "notice-completeness",
                    summary_ev,
                    summary=(
                        f"NOTICE file covers all {len(all_holders)} "
                        "detected copyright holder(s)."
                    ),
                    evidence_locator="NOTICE",
                )
            ],
        )

    @staticmethod
    def _resolve_repo_path(context: Any) -> Path | None:
        if context and hasattr(context, "target"):
            return Path(context.target)
        return None

    @staticmethod
    def _read_notice(repo_path: Path | None) -> str | None:
        if repo_path is None:
            return None
        for name in ("NOTICE", "NOTICE.md", "NOTICE.txt"):
            p = repo_path / name
            if p.is_file():
                try:
                    return p.read_text(encoding="utf-8")
                except OSError as e:
                    logger.debug("Failed to read NOTICE file %s: %s", p, e)
                    return None
        return None


def _register() -> None:
    if "HYG-LIC-002" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-LIC-002", NoticeCompletenessRule())


_register()

__all__ = ["NoticeCompletenessRule"]
