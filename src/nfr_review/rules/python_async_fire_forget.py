# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: python-async-fire-and-forget — detects fire-and-forget async patterns."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.python_ast import PythonAstFilePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class PythonAsyncFireForgetRule(FieldRule[PythonAstFilePayload]):
    """Flag asyncio.create_task() calls where the returned Task is not stored."""

    id = "python-async-fire-and-forget"
    collector_name = "python-ast"
    evidence_kind = "python-ast-file"
    payload_type = PythonAstFilePayload
    pattern_tag = "async-fire-and-forget"
    default_confidence = 0.85
    all_clear_summary = "No fire-and-forget async patterns detected."
    all_clear_recommendation = "No action required."

    def check(self, payload: PythonAstFilePayload, ev: Evidence) -> Iterable[Hit]:
        file_path = payload.file_path
        for call in payload.async_calls:
            if not call.stored:
                yield Hit(
                    rag="amber",
                    severity="medium",
                    summary=f"Fire-and-forget {call.call}()",
                    recommendation=(
                        "Store Task reference and add done_callback"
                        " for error handling; GC can collect unstored tasks."
                    ),
                    locator=f"{file_path}:{call.line}",
                )


__all__ = ["PythonAsyncFireForgetRule"]
