# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: resilience-annotation-missing.

Flags classes using HTTP clients that lack resilience annotations.
"""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.java_ast import JavaAstFilePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit

_HTTP_CLIENT_PATTERNS = frozenset({"RestTemplate", "WebClient", "FeignClient"})

_RESILIENCE_ANNOTATIONS = frozenset(
    {
        "CircuitBreaker",
        "Retry",
        "Bulkhead",
        "RateLimiter",
    }
)


class ResilienceAnnotationMissingRule(FieldRule[JavaAstFilePayload]):
    """Flag classes that import HTTP clients but lack resilience annotations."""

    id = "resilience-annotation-missing"
    collector_name = "java-ast"
    evidence_kind = "java-ast-file"
    payload_type = JavaAstFilePayload
    pattern_tag = "resilience-pattern"
    default_confidence = 0.8
    all_clear_summary = (
        "All HTTP-client classes have resilience annotations, or no HTTP clients found."
    )
    all_clear_recommendation = "No action required."

    def check(self, payload: JavaAstFilePayload, ev: Evidence) -> Iterable[Hit]:
        uses_http_client = any(
            any(pattern in imp for imp in payload.imports) for pattern in _HTTP_CLIENT_PATTERNS
        )
        if not uses_http_client:
            return

        for cls in payload.classes:
            class_annotations = set(cls.annotations)
            method_annotations: set[str] = set()
            for method in cls.methods:
                method_annotations.update(method.annotations)

            all_annotations = class_annotations | method_annotations
            has_resilience = bool(all_annotations & _RESILIENCE_ANNOTATIONS)

            if not has_resilience:
                yield Hit(
                    rag="amber",
                    severity="high",
                    summary=(
                        f"Class {cls.name} uses HTTP client but has no resilience annotations."
                    ),
                    recommendation=(
                        "Add @CircuitBreaker, @Retry, or"
                        " @Bulkhead to service methods making"
                        " external calls."
                    ),
                    locator=f"{payload.file_path}:{cls.name}",
                )


__all__ = ["ResilienceAnnotationMissingRule"]
