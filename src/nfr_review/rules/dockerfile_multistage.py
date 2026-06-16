# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: dockerfile-multistage — suggests multi-stage builds for single-stage Dockerfiles."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding


class DockerfileMultistageRule:
    """Suggest multi-stage builds when a single-stage Dockerfile has RUN commands."""

    id = "dockerfile-multistage"
    band: Band = 1
    required_collectors: list[str] = ["dockerfile"]
    required_tech: list[str] = ["dockerfile"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        df_evidence = filter_evidence(evidence, "dockerfile", "dockerfile-analysis")
        if not df_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no dockerfile evidence available",
            )

        findings: list[Finding] = []
        for ev in df_evidence:
            file_path = ev.payload.file_path
            is_multistage = ev.payload.is_multistage
            run_commands = ev.payload.run_commands

            if not is_multistage and len(run_commands) > 0:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="low",
                        summary=(
                            f"Dockerfile '{file_path}' uses a single-stage"
                            f" build with {len(run_commands)} RUN command(s)."
                        ),
                        recommendation=(
                            "Consider a multi-stage build to separate build"
                            " dependencies from the runtime image, reducing"
                            " final image size and attack surface."
                        ),
                        evidence_locator=file_path,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.7,
                        pattern_tag="dockerfile-multistage",
                    )
                )

        if not findings:
            first = df_evidence[0]
            findings.append(
                make_green_finding(
                    self.id,
                    "dockerfile-multistage",
                    first,
                    summary="All Dockerfiles use multi-stage builds.",
                    recommendation="No action required — multi-stage builds in use.",
                    confidence=0.7,
                    evidence_locator="all-dockerfiles",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "dockerfile-multistage" not in rule_registry:
        rule_registry.register("dockerfile-multistage", DockerfileMultistageRule())


_register()

__all__ = ["DockerfileMultistageRule"]
