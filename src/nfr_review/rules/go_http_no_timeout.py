# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: go-http-no-timeout — detects HTTP calls without explicit timeouts."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.go_ast import GoAstFilePayload
from nfr_review.models import Evidence, compute_content_hash
from nfr_review.rules.framework import FieldRule, Hit

_DEFAULT_CLIENT_CALLS = frozenset({"http.Get", "http.Post", "http.Head", "http.PostForm"})


class GoHttpNoTimeoutRule(FieldRule[GoAstFilePayload]):
    """Flag HTTP calls using DefaultClient or Client without Timeout."""

    id = "go-http-no-timeout"
    collector_name = "go-ast"
    evidence_kind = "go-ast-file"
    payload_type = GoAstFilePayload
    pattern_tag = "go-http-no-timeout"
    default_confidence = 0.9
    all_clear_summary = "No HTTP calls without timeouts detected."

    def check(self, payload: GoAstFilePayload, ev: Evidence) -> Iterable[Hit]:
        for call in payload.http_calls:
            call_name = call.call
            if call_name in _DEFAULT_CLIENT_CALLS:
                yield Hit(
                    rag="red",
                    severity="high",
                    summary=f"{call_name}() uses DefaultClient with no timeout",
                    recommendation=(
                        "Use an http.Client with an explicit Timeout"
                        " instead of the package-level convenience functions."
                    ),
                    locator=f"{payload.file_path}:{call.line}",
                    confidence=0.95,
                    content_hash=compute_content_hash(getattr(call, "source_line", call_name)),
                )
            elif call_name == "http.Client" and not call.has_timeout:
                yield Hit(
                    rag="amber",
                    severity="medium",
                    summary="http.Client without Timeout",
                    recommendation=(
                        "Set an explicit Timeout on the http.Client"
                        " to prevent indefinite hangs."
                    ),
                    locator=f"{payload.file_path}:{call.line}",
                    content_hash=compute_content_hash(getattr(call, "source_line", call_name)),
                )


__all__ = ["GoHttpNoTimeoutRule"]
