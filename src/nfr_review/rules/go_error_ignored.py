# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: go-error-ignored — detects ignored error return values in Go code."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.go_ast import GoAstFilePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class GoErrorIgnoredRule(FieldRule[GoAstFilePayload]):
    """Flag Go error return values that are explicitly ignored via blank identifier."""

    id = "go-error-ignored"
    collector_name = "go-ast"
    evidence_kind = "go-ast-file"
    payload_type = GoAstFilePayload
    pattern_tag = "go-error-ignored"
    all_clear_summary = "No ignored error return values detected."

    def check(self, payload: GoAstFilePayload, ev: Evidence) -> Iterable[Hit]:
        for entry in payload.error_assignments:
            if entry.error_ignored:
                yield Hit(
                    rag="amber",
                    severity="medium",
                    summary=f"Ignored error from {entry.call}()",
                    recommendation=(
                        "Handle the error or explicitly document why it is safe to ignore."
                    ),
                    locator=f"{payload.file_path}:{entry.line}",
                )


__all__ = ["GoErrorIgnoredRule"]
