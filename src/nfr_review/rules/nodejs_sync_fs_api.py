# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: nodejs-sync-fs-api — detects sync FS calls blocking the loop."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.nodejs_ast import NodejsAstFilePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class NodejsSyncFsApiRule(FieldRule[NodejsAstFilePayload]):
    """Flag synchronous filesystem and child_process calls that block the event loop."""

    id = "nodejs-sync-fs-api"
    collector_name = "nodejs-ast"
    evidence_kind = "nodejs-ast-file"
    payload_type = NodejsAstFilePayload
    pattern_tag = "nodejs-sync-fs-api"
    all_clear_summary = "No synchronous blocking calls detected."

    def check(self, payload: NodejsAstFilePayload, ev: Evidence) -> Iterable[Hit]:
        for call in payload.sync_calls:
            yield Hit(
                rag="amber",
                severity="medium",
                summary=f"Synchronous call {call.method}()",
                recommendation=(
                    "Use the async equivalent to avoid blocking the"
                    " event loop in production code."
                ),
                locator=f"{payload.file_path}:{call.line}",
            )


__all__ = ["NodejsSyncFsApiRule"]
