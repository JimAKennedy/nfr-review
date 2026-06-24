# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: actuator-exposure-risk -- flags unprotected Spring Boot actuator endpoints."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, cast

from nfr_review.collectors.payloads.spring import SpringConfigFilePayload
from nfr_review.models import Evidence, Severity
from nfr_review.rules.framework import FieldRule, Hit

_SENSITIVE_ENDPOINTS = frozenset(
    {
        "env",
        "configprops",
        "beans",
        "heapdump",
        "threaddump",
        "mappings",
    }
)
_PROD_PROFILES = frozenset({"prod", "production", "prd"})


class ActuatorExposureRiskRule(FieldRule[SpringConfigFilePayload]):
    """Flag when actuator endpoints are exposed without restriction."""

    id = "actuator-exposure-risk"
    collector_name = "spring-config"
    evidence_kind = "spring-config-file"
    payload_type = SpringConfigFilePayload
    pattern_tag = "actuator-exposure"
    required_tech = ["spring_boot"]
    default_confidence = 0.85
    all_clear_summary = "Actuator endpoints are properly restricted."
    all_clear_recommendation = "No action required."

    def check(self, payload: SpringConfigFilePayload, ev: Evidence) -> Iterable[Hit]:
        actuator = payload.actuator or {}
        include_val = actuator.get("include", "")
        exclude_val = actuator.get("exclude", "")

        include_str = str(include_val) if include_val else ""
        exclude_str = str(exclude_val) if exclude_val else ""

        if not include_str:
            return

        management = payload.management or {}
        server = payload.server or {}
        mgmt_port = _deep_str(management, "server", "port")
        server_port = _deep_str(server, "port")
        profile = payload.profile
        is_prod = profile and profile.lower() in _PROD_PROFILES
        file_path = payload.file_path

        if include_str == "*":
            exposed_sensitive = _SENSITIVE_ENDPOINTS - _parse_endpoint_set(exclude_str)
            if exposed_sensitive:
                sev = cast(Severity, "high" if is_prod else "medium")
                yield Hit(
                    rag="red" if is_prod else "amber",
                    severity=sev,
                    summary=(
                        f"Actuator wildcard include exposes sensitive"
                        f" endpoints ({', '.join(sorted(exposed_sensitive))})"
                        f" in {file_path}"
                    ),
                    recommendation=(
                        "Restrict management.endpoints.web.exposure.include"
                        " to only needed endpoints (health, info, prometheus)"
                        " or add sensitive endpoints to the exclude list."
                    ),
                    locator=file_path,
                )
                if is_prod and mgmt_port and server_port and mgmt_port == server_port:
                    yield Hit(
                        rag="red",
                        severity="high",
                        summary=(
                            f"Management port equals server port ({mgmt_port})"
                            f" with sensitive endpoints exposed in {file_path}"
                        ),
                        recommendation=(
                            "Move management endpoints to a separate port"
                            " (management.server.port) not exposed to public traffic."
                        ),
                        locator=file_path,
                        confidence=0.9,
                    )
                return

        exposed = _parse_endpoint_set(include_str)
        exposed_sensitive_set = exposed & _SENSITIVE_ENDPOINTS
        if exposed_sensitive_set:
            sev2 = cast(Severity, "high" if is_prod else "medium")
            yield Hit(
                rag="red" if is_prod else "amber",
                severity=sev2,
                summary=(
                    f"Sensitive actuator endpoints explicitly exposed"
                    f" ({', '.join(sorted(exposed_sensitive_set))})"
                    f" in {file_path}"
                ),
                recommendation=(
                    "Remove sensitive endpoints from"
                    " management.endpoints.web.exposure.include"
                    " unless required for monitoring."
                ),
                locator=file_path,
            )


def _deep_str(d: dict[str, Any], *keys: str) -> str | None:
    current: Any = d
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return str(current) if current is not None else None


def _parse_endpoint_set(val: str) -> set[str]:
    return {s.strip().lower() for s in val.split(",") if s.strip()}


__all__ = ["ActuatorExposureRiskRule"]
