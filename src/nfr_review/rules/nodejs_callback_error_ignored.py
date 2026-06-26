# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: nodejs-callback-error-ignored — detects callbacks that ignore the error parameter."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.nodejs_ast import NodejsAstFilePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class NodejsCallbackErrorIgnoredRule(FieldRule[NodejsAstFilePayload]):
    """Flag Node.js callbacks that receive an error parameter but never check it."""

    id = "nodejs-callback-error-ignored"
    collector_name = "nodejs-ast"
    evidence_kind = "nodejs-ast-file"
    payload_type = NodejsAstFilePayload
    pattern_tag = "nodejs-callback-error-ignored"
    default_confidence = 0.85
    all_clear_summary = "No ignored callback errors detected."

    def check(self, payload: NodejsAstFilePayload, ev: Evidence) -> Iterable[Hit]:
        for cb in payload.callback_patterns:
            if not cb.checks_error:
                yield Hit(
                    rag="amber",
                    severity="medium",
                    summary=f"Callback ignores error parameter '{cb.callback_param}'",
                    recommendation=(
                        "Check the error parameter and handle or propagate"
                        " it. Ignored errors cause silent failures."
                    ),
                    locator=f"{payload.file_path}:{cb.line}",
                )


__all__ = ["NodejsCallbackErrorIgnoredRule"]
