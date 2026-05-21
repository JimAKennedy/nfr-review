# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: logging-config-missing — flags lack of structured logging configuration."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry

_JSON_INDICATORS = frozenset(
    {
        "json",
        "logstash",
        "jsonlayout",
        "structuredlogprovider",
    }
)


class LoggingConfigMissingRule:
    """Flag when no structured logging (JSON/logstash encoder) is configured."""

    id = "logging-config-missing"
    band: Band = 1
    required_collectors: list[str] = ["spring-config"]
    required_tech: list[str] = ["spring_boot"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        spring_evidence = [
            e
            for e in evidence
            if e.collector_name == "spring-config" and e.kind == "spring-config-file"
        ]
        if not spring_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no spring-config evidence available",
            )

        for ev in spring_evidence:
            payload = ev.payload
            logging_section = payload.get("logging", {}) or {}
            raw_keys = payload.get("raw_keys", [])

            if _has_structured_logging(logging_section, raw_keys):
                file_path = payload.get("file_path", ev.locator)
                return RuleResult(
                    rule_id=self.id,
                    findings=[
                        Finding(
                            rule_id=self.id,
                            rag="green",
                            severity="info",
                            summary=(
                                f"Structured logging configuration detected in {file_path}."
                            ),
                            recommendation="No action required.",
                            evidence_locator=file_path,
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.8,
                            pattern_tag="logging-config",
                        )
                    ],
                )

        file_path = spring_evidence[0].payload.get("file_path", spring_evidence[0].locator)
        return RuleResult(
            rule_id=self.id,
            findings=[
                Finding(
                    rule_id=self.id,
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
                    evidence_locator=file_path,
                    collector_name=spring_evidence[0].collector_name,
                    collector_version=spring_evidence[0].collector_version,
                    confidence=0.75,
                    pattern_tag="logging-config",
                )
            ],
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


def _register() -> None:
    if "logging-config-missing" not in rule_registry:
        rule_registry.register("logging-config-missing", LoggingConfigMissingRule())


_register()

__all__ = ["LoggingConfigMissingRule"]
