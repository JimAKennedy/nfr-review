"""Rule: dockerfile-user-directive — flags Dockerfiles running as root."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry


class DockerfileUserDirectiveRule:
    """Flag Dockerfiles that lack a USER directive (running as root)."""

    id = "dockerfile-user-directive"
    band: Band = 1
    required_collectors: list[str] = ["dockerfile"]
    required_tech: list[str] = ["dockerfile"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        df_evidence = [
            e
            for e in evidence
            if e.collector_name == "dockerfile" and e.kind == "dockerfile-analysis"
        ]
        if not df_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no dockerfile evidence available",
            )

        findings: list[Finding] = []
        for ev in df_evidence:
            file_path = ev.payload.get("file_path", ev.locator)
            has_user = ev.payload.get("has_user_directive", False)

            if not has_user:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="high",
                        summary=(
                            f"Dockerfile '{file_path}' has no USER directive —"
                            " container runs as root."
                        ),
                        recommendation=(
                            "Add a USER directive to run the container as a"
                            " non-root user, reducing the blast radius of"
                            " container escapes."
                        ),
                        evidence_locator=file_path,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.95,
                        pattern_tag="dockerfile-user-directive",
                    )
                )

        if not findings:
            first = df_evidence[0]
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary="All Dockerfiles specify a USER directive.",
                    recommendation="No action required — non-root user configured.",
                    evidence_locator="all-dockerfiles",
                    collector_name=first.collector_name,
                    collector_version=first.collector_version,
                    confidence=0.95,
                    pattern_tag="dockerfile-user-directive",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "dockerfile-user-directive" not in rule_registry:
        rule_registry.register("dockerfile-user-directive", DockerfileUserDirectiveRule())


_register()

__all__ = ["DockerfileUserDirectiveRule"]
