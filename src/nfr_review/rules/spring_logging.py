# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: logging-config-missing -- flags lack of structured logging configuration."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from nfr_review.collectors.payloads.spring import SpringConfigFilePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit

_JSON_INDICATORS = frozenset(
    {
        "json",
        "logstash",
        "jsonlayout",
        "structuredlogprovider",
    }
)


class LoggingConfigMissingRule(FieldRule[SpringConfigFilePayload]):
    """Flag when no structured logging (JSON/logstash encoder) is configured."""

    id = "logging-config-missing"
    collector_name = "spring-config"
    evidence_kind = "spring-config-file"
    payload_type = SpringConfigFilePayload
    pattern_tag = "logging-config"
    required_tech = ["spring_boot"]
    default_confidence = 0.75
    all_clear_summary = "Structured logging configuration detected."
    all_clear_recommendation = "No action required."

    def check(self, payload: SpringConfigFilePayload, ev: Evidence) -> Iterable[Hit]:
        logging_section = payload.logging or {}

        if _has_structured_logging(logging_section, payload.raw_keys):
            return

        yield Hit(
            rag="amber",
            severity="low",
            summary=(
                "No structured logging configuration detected."
                " Text-based logs are harder to parse in production."
            ),
            recommendation=(
                "Configure a JSON or Logstash encoder"
                " (e.g. logback-spring.xml with JsonLayout"
                " or logging.pattern.console with JSON format)"
                " for machine-readable log output."
            ),
            locator=payload.file_path,
        )


def _has_structured_logging(
    logging_section: dict[str, Any],
    raw_keys: list[str],
) -> bool:
    values_str = _flatten_values(logging_section).lower()
    if any(indicator in values_str for indicator in _JSON_INDICATORS):
        return True
    if "logback" in values_str:
        return True
    for key in raw_keys:
        if "logback" in str(key).lower():
            return True
    return False


def _flatten_values(d: dict[str, Any]) -> str:
    parts: list[str] = []
    for v in d.values():
        if isinstance(v, dict):
            parts.append(_flatten_values(v))
        else:
            parts.append(str(v))
    return " ".join(parts)


__all__ = ["LoggingConfigMissingRule"]
