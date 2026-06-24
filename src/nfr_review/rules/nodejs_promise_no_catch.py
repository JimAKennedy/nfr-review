# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: nodejs-promise-no-catch — detects .then() chains without .catch() error handling."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.nodejs_ast import NodejsAstFilePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class NodejsPromiseNoCatchRule(FieldRule[NodejsAstFilePayload]):
    """Flag .then() promise chains that lack .catch() error handling."""

    id = "nodejs-promise-no-catch"
    collector_name = "nodejs-ast"
    evidence_kind = "nodejs-ast-file"
    payload_type = NodejsAstFilePayload
    pattern_tag = "nodejs-promise-no-catch"
    default_confidence = 0.85
    all_clear_summary = "All .then() chains have proper .catch() handling."

    def check(self, payload: NodejsAstFilePayload, ev: Evidence) -> Iterable[Hit]:
        for chain in payload.promise_chains:
            if not chain.has_catch:
                yield Hit(
                    rag="amber",
                    severity="medium",
                    summary=".then() chain without .catch()",
                    recommendation=(
                        "Add .catch() to the promise chain or convert"
                        " to async/await with try/catch for proper"
                        " error handling."
                    ),
                    locator=f"{payload.file_path}:{chain.line}",
                )


__all__ = ["NodejsPromiseNoCatchRule"]
