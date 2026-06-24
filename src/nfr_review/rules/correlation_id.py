# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: correlation-id-missing — flags Java/Spring projects lacking tracing libraries."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.deps import DepsPayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit

_TRACING_EXACT: frozenset[str] = frozenset(
    {
        "org.springframework.cloud:spring-cloud-starter-sleuth",
        "io.micrometer:micrometer-tracing",
        "io.opentelemetry:opentelemetry-api",
    }
)

_TRACING_PREFIXES: tuple[str, ...] = (
    "io.micrometer:micrometer-tracing-bridge-",
    "io.opentelemetry.instrumentation:",
)


def _is_tracing_dep(name: str) -> bool:
    if name in _TRACING_EXACT:
        return True
    return any(name.startswith(prefix) for prefix in _TRACING_PREFIXES)


class CorrelationIdMissingRule(FieldRule[DepsPayload]):
    id = "correlation-id-missing"
    collector_name = "java-deps"
    evidence_kind = "java-deps"
    payload_type = DepsPayload
    pattern_tag = "correlation-id"
    required_tech = ["java"]
    default_confidence = 0.85
    all_clear_summary = "Distributed tracing / correlation-ID library is present."
    all_clear_recommendation = "No action required — a tracing library is on the classpath."

    def check(self, payload: DepsPayload, ev: Evidence) -> Iterable[Hit]:
        has_tracing = any(_is_tracing_dep(dep.name) for dep in payload.dependencies)
        if not has_tracing:
            locator = (
                payload.manifest_files_found[0] if payload.manifest_files_found else ev.locator
            )
            yield Hit(
                rag="amber",
                severity="medium",
                summary=(
                    "No distributed tracing or correlation-ID library found."
                    " Requests cannot be correlated across service boundaries."
                ),
                recommendation=(
                    "Add one of the following to your dependencies:"
                    " io.micrometer:micrometer-tracing-bridge-brave (Spring Boot 3+),"
                    " org.springframework.cloud:spring-cloud-starter-sleuth"
                    " (Spring Boot 2),"
                    " or io.opentelemetry:opentelemetry-api with an SDK implementation."
                ),
                locator=locator,
            )


__all__ = ["CorrelationIdMissingRule"]
