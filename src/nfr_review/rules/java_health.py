"""Rule: health-endpoint-missing — checks for health endpoint in Spring controllers."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry

_HEALTH_PATHS = frozenset({"/health", "/actuator/health"})


class HealthEndpointMissingRule:
    """Flag when no @RestController exposes a health-check endpoint."""

    id = "health-endpoint-missing"
    band: Band = 1
    required_collectors: list[str] = ["java-ast"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        java_evidence = [
            e
            for e in evidence
            if e.collector_name == "java-ast" and e.kind == "java-ast-file"
        ]
        if not java_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no java-ast evidence available",
            )

        for ev in java_evidence:
            for cls in ev.payload.get("classes", []):
                if "RestController" not in cls.get("annotations", []):
                    continue
                for method in cls.get("methods", []):
                    for path in method.get("mapping_paths", []):
                        if path in _HEALTH_PATHS:
                            file_ref = ev.payload.get(
                                "file_path", ev.locator
                            )
                            locator = f"{file_ref}:{cls['name']}"
                            return RuleResult(
                                rule_id=self.id,
                                findings=[
                                    Finding(
                                        rule_id=self.id,
                                        rag="green",
                                        severity="info",
                                        summary=(
                                            f"Health endpoint found:"
                                            f" {path} in {cls['name']}"
                                        ),
                                        recommendation=(
                                            "No action required"
                                            " — health endpoint is present."
                                        ),
                                        evidence_locator=locator,
                                        collector_name=ev.collector_name,
                                        collector_version=ev.collector_version,
                                        confidence=0.9,
                                        pattern_tag="health-endpoint",
                                    )
                                ],
                            )

        actuator_health = self._detect_actuator_health(evidence)
        if actuator_health:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    Finding(
                        rule_id=self.id,
                        rag="green",
                        severity="info",
                        summary=(
                            "Health endpoint available via Spring Boot"
                            " Actuator auto-configuration."
                        ),
                        recommendation=(
                            "No action required — Actuator exposes"
                            " /actuator/health automatically."
                        ),
                        evidence_locator=actuator_health,
                        collector_name="spring-config",
                        collector_version="0.1.0",
                        confidence=0.8,
                        pattern_tag="health-endpoint",
                    )
                ],
            )

        return RuleResult(
            rule_id=self.id,
            findings=[
                Finding(
                    rule_id=self.id,
                    rag="amber",
                    severity="medium",
                    summary=(
                        "No health endpoint (/health or"
                        " /actuator/health) detected in any"
                        " @RestController, and no Actuator"
                        " auto-configuration found."
                    ),
                    recommendation=(
                        "Add a health-check endpoint (e.g. Spring"
                        " Boot Actuator /actuator/health) to enable"
                        " liveness/readiness probes."
                    ),
                    evidence_locator="project-wide",
                    collector_name=java_evidence[0].collector_name,
                    collector_version=java_evidence[0].collector_version,
                    confidence=0.9,
                    pattern_tag="health-endpoint",
                )
            ],
        )

    @staticmethod
    def _detect_actuator_health(evidence: list[Evidence]) -> str | None:
        """Check spring-config evidence for Actuator health endpoint exposure.

        Spring Boot exposes /actuator/health by default when the actuator
        starter is on the classpath. Any management.* config implies Actuator
        is present. Health is available unless explicitly excluded.
        """
        for ev in evidence:
            if ev.collector_name != "spring-config" or ev.kind != "spring-config-file":
                continue
            management = ev.payload.get("management", {})
            if not management:
                continue
            actuator = ev.payload.get("actuator", {})
            exclude = actuator.get("exclude", "")
            exclude_str = (
                exclude if isinstance(exclude, str)
                else ",".join(str(i) for i in exclude) if isinstance(exclude, list)
                else ""
            )
            if "health" in exclude_str:
                continue
            return ev.payload.get("file_path", ev.locator)
        return None


def _register() -> None:
    if "health-endpoint-missing" not in rule_registry:
        rule_registry.register("health-endpoint-missing", HealthEndpointMissingRule())


_register()

__all__ = ["HealthEndpointMissingRule"]
