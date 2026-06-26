# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Detects catching Exception/BaseException without logging or re-raising."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.python_ast import PythonAstFilePayload
from nfr_review.models import Evidence, compute_content_hash
from nfr_review.rules.framework import FieldRule, Hit

_BROAD_TYPES = frozenset({"Exception", "BaseException"})


class PythonBroadExceptSilentRule(FieldRule[PythonAstFilePayload]):
    """Flag catch blocks that silently swallow Exception/BaseException."""

    id = "python-broad-except-silent"
    collector_name = "python-ast"
    evidence_kind = "python-ast-file"
    payload_type = PythonAstFilePayload
    pattern_tag = "broad-except-silent"
    default_confidence = 0.9
    all_clear_summary = "No silently swallowed broad exceptions detected."

    def check(self, payload: PythonAstFilePayload, ev: Evidence) -> Iterable[Hit]:
        for block in payload.catch_blocks:
            if (
                block.caught_type in _BROAD_TYPES
                and not block.rethrows
                and not block.has_logging
            ):
                yield Hit(
                    rag="red",
                    summary=(f"Silent catch({block.caught_type}) without logging or rethrow"),
                    recommendation=(
                        "At minimum log the exception; prefer re-raising"
                        " or catching specific exception types."
                    ),
                    locator=f"{payload.file_path}:{block.line}",
                    content_hash=compute_content_hash(block.caught_type),
                )


__all__ = ["PythonBroadExceptSilentRule"]
