# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: csharp-disposable-no-using — detects IDisposable creation without using statement."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.csharp_ast import CSharpAstFilePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit

_DISPOSABLE_TYPES = frozenset(
    {
        "FileStream",
        "StreamReader",
        "StreamWriter",
        "SqlConnection",
        "SqlCommand",
        "HttpClient",
        "MemoryStream",
        "BinaryReader",
        "BinaryWriter",
        "TcpClient",
        "NetworkStream",
    }
)


class CSharpDisposableNoUsingRule(FieldRule[CSharpAstFilePayload]):
    """Flag IDisposable object creation not wrapped in a using statement."""

    id = "csharp-disposable-no-using"
    collector_name = "csharp-ast"
    evidence_kind = "csharp-ast-file"
    payload_type = CSharpAstFilePayload
    pattern_tag = "csharp-disposable-no-using"
    default_confidence = 0.85
    all_clear_summary = "All IDisposable objects properly wrapped in using."

    def check(self, payload: CSharpAstFilePayload, ev: Evidence) -> Iterable[Hit]:
        for creation in payload.object_creations:
            if creation.type_name in _DISPOSABLE_TYPES and not creation.in_using:
                yield Hit(
                    rag="amber",
                    severity="medium",
                    summary=f"{creation.type_name} created without using statement",
                    recommendation=(
                        "Wrap IDisposable objects in a using statement or"
                        " using declaration to ensure proper resource cleanup."
                    ),
                    locator=f"{payload.file_path}:{creation.line}",
                )


__all__ = ["CSharpDisposableNoUsingRule"]
