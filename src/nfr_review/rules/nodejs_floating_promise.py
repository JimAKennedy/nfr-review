# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: nodejs-floating-promise — detects unhandled promise rejections in Node.js code."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.nodejs_ast import NodejsAstFilePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class NodejsFloatingPromiseRule(FieldRule[NodejsAstFilePayload]):
    """Flag promise chains without .catch() that risk unhandled rejections."""

    id = "nodejs-floating-promise"
    collector_name = "nodejs-ast"
    evidence_kind = "nodejs-ast-file"
    payload_type = NodejsAstFilePayload
    pattern_tag = "nodejs-floating-promise"
    all_clear_summary = "No floating promises detected."

    def check(self, payload: NodejsAstFilePayload, ev: Evidence) -> Iterable[Hit]:
        for chain in payload.promise_chains:
            if not chain.has_catch:
                yield Hit(
                    rag="red",
                    severity="high",
                    summary="Floating promise without .catch()",
                    recommendation=(
                        "Add .catch() or use try/await to handle"
                        " rejection. Unhandled promise rejections crash"
                        " Node.js processes."
                    ),
                    locator=f"{payload.file_path}:{chain.line}",
                )


__all__ = ["NodejsFloatingPromiseRule"]
