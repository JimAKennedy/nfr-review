"""Rule: actuator-exposure-risk — flags unprotected Spring Boot actuator endpoints."""

from __future__ import annotations

from typing import Any, cast

from nfr_review.models import Evidence, Finding, RuleResult, Severity
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry

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


class ActuatorExposureRiskRule:
    """Flag when actuator endpoints are exposed without restriction."""

    id = "actuator-exposure-risk"
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

        findings: list[Finding] = []

        for ev in spring_evidence:
            payload = ev.payload
            actuator = payload.get("actuator", {}) or {}
            include_val = actuator.get("include", "")
            exclude_val = actuator.get("exclude", "")

            include_str = str(include_val) if include_val else ""
            exclude_str = str(exclude_val) if exclude_val else ""

            if not include_str:
                continue

            management = payload.get("management", {}) or {}
            server = payload.get("server", {}) or {}
            mgmt_port = _deep_str(management, "server", "port")
            server_port = _deep_str(server, "port")
            profile = payload.get("profile")
            is_prod = profile and profile.lower() in _PROD_PROFILES
            file_path = payload.get("file_path", ev.locator)

            if include_str == "*":
                exposed_sensitive = _SENSITIVE_ENDPOINTS - _parse_endpoint_set(exclude_str)
                if exposed_sensitive:
                    sev = cast(Severity, "high" if is_prod else "medium")
                    findings.append(
                        Finding(
                            rule_id=self.id,
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
                            evidence_locator=file_path,
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.85,
                            pattern_tag="actuator-exposure",
                        )
                    )
                    if is_prod and mgmt_port and server_port and mgmt_port == server_port:
                        findings.append(
                            Finding(
                                rule_id=self.id,
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
                                evidence_locator=file_path,
                                collector_name=ev.collector_name,
                                collector_version=ev.collector_version,
                                confidence=0.9,
                                pattern_tag="actuator-exposure",
                            )
                        )
                    continue

            exposed = _parse_endpoint_set(include_str)
            exposed_sensitive_set = exposed & _SENSITIVE_ENDPOINTS
            if exposed_sensitive_set:
                sev2 = cast(Severity, "high" if is_prod else "medium")
                findings.append(
                    Finding(
                        rule_id=self.id,
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
                        evidence_locator=file_path,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.85,
                        pattern_tag="actuator-exposure",
                    )
                )

        if not findings:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    Finding(
                        rule_id=self.id,
                        rag="green",
                        severity="info",
                        summary="Actuator endpoints are properly restricted.",
                        recommendation="No action required.",
                        evidence_locator=spring_evidence[0].payload.get(
                            "file_path", spring_evidence[0].locator
                        ),
                        collector_name=spring_evidence[0].collector_name,
                        collector_version=spring_evidence[0].collector_version,
                        confidence=0.8,
                        pattern_tag="actuator-exposure",
                    )
                ],
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _deep_str(d: dict[str, Any], *keys: str) -> str | None:
    current: Any = d
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return str(current) if current is not None else None


def _parse_endpoint_set(val: str) -> set[str]:
    return {s.strip().lower() for s in val.split(",") if s.strip()}


def _register() -> None:
    if "actuator-exposure-risk" not in rule_registry:
        rule_registry.register("actuator-exposure-risk", ActuatorExposureRiskRule())


_register()

__all__ = ["ActuatorExposureRiskRule"]
