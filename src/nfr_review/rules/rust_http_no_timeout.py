# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: rust-http-no-timeout — detects reqwest clients built without an
explicit timeout.
"""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.rust_ast import RustAstFilePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class RustHttpNoTimeoutRule(FieldRule[RustAstFilePayload]):
    """Flag reqwest::Client instances built without an explicit timeout."""

    id = "rust-http-no-timeout"
    collector_name = "rust-ast"
    evidence_kind = "rust-ast-file"
    payload_type = RustAstFilePayload
    pattern_tag = "rust-http-no-timeout"
    required_tech: list[str] = ["rust"]
    default_confidence = 0.9
    all_clear_summary = "No reqwest clients without an explicit timeout detected."

    def check(self, payload: RustAstFilePayload, ev: Evidence) -> Iterable[Hit]:
        for build in payload.http_client_builds:
            if build.has_timeout:
                continue
            if build.call == "reqwest::Client::new":
                yield Hit(
                    rag="red",
                    severity="high",
                    summary=(
                        "reqwest::Client::new() has no timeout —"
                        " requests can hang indefinitely"
                    ),
                    recommendation=(
                        "Use reqwest::Client::builder().timeout(...).build()"
                        " instead of Client::new()."
                    ),
                    locator=f"{payload.file_path}:{build.line}",
                    confidence=0.95,
                )
            else:
                yield Hit(
                    rag="amber",
                    severity="medium",
                    summary="reqwest client built via builder() without .timeout(...)",
                    recommendation=(
                        "Add an explicit .timeout(...) call to the client builder chain."
                    ),
                    locator=f"{payload.file_path}:{build.line}",
                )


__all__ = ["RustHttpNoTimeoutRule"]
