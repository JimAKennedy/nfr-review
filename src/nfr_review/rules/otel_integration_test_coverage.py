# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""otel-integration-test-coverage: flags repos where API endpoints lack integration tests."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.rules.framework import register
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding


@register
class OTelIntegrationTestCoverageRule:
    """Flag repos where API endpoints lack corresponding integration tests."""

    id = "otel-integration-test-coverage"
    band: Band = 1
    required_collectors: list[str] = ["repo-structure"]
    required_tech: list[str] = []

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        java_ast_evidence = filter_evidence(evidence, "java-ast", "java-ast-file")

        if not java_ast_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no java-ast-file evidence available",
            )

        controllers: list[dict[str, Any]] = []
        test_files: set[str] = set()

        for ev in java_ast_evidence:
            file_path = ev.payload.file_path
            classes = ev.payload.classes

            is_test = "/test/" in file_path or file_path.endswith("Test.java")
            if is_test:
                test_files.add(file_path)
                continue

            for cls in classes:
                if not isinstance(cls, dict):
                    continue
                annotations = cls.get("annotations", [])
                ann_names = [
                    a.get("name", "") if isinstance(a, dict) else str(a) for a in annotations
                ]
                is_controller = any(
                    "Controller" in a or "RestController" in a for a in ann_names
                )
                if not is_controller:
                    continue

                methods = cls.get("methods", [])
                endpoints: list[str] = []
                for m in methods:
                    if not isinstance(m, dict):
                        continue
                    m_annotations = m.get("annotations", [])
                    mapping_paths = m.get("mapping_paths", [])
                    if mapping_paths:
                        endpoints.extend(mapping_paths)
                    elif any(
                        "Mapping" in (a.get("name", "") if isinstance(a, dict) else str(a))
                        for a in m_annotations
                    ):
                        endpoints.append(m.get("name", "unknown"))

                if endpoints:
                    controllers.append(
                        {
                            "class_name": cls.get("name", "Unknown"),
                            "file_path": file_path,
                            "endpoints": endpoints,
                        }
                    )

        if not controllers:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no controller classes found in java-ast evidence",
            )

        first = java_ast_evidence[0]
        untested: list[dict[str, Any]] = []

        for ctrl in controllers:
            ctrl_name = ctrl["class_name"]
            has_test = any(
                ctrl_name in tf or ctrl_name.replace("Controller", "") in tf
                for tf in test_files
            )
            if not has_test:
                untested.append(ctrl)

        if not untested:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_green_finding(
                        self.id,
                        "otel-integration-test-coverage",
                        first,
                        summary=(
                            f"All {len(controllers)} controller(s) have "
                            "corresponding integration tests."
                        ),
                        confidence=0.8,
                        evidence_locator=first.locator,
                    )
                ],
            )

        untested_names = [c["class_name"] for c in untested]
        return RuleResult(
            rule_id=self.id,
            findings=[
                Finding(
                    rule_id=self.id,
                    rag="amber",
                    severity="medium",
                    summary=(
                        f"{len(untested)} of {len(controllers)} controller(s) "
                        f"lack integration tests: {', '.join(untested_names)}."
                    ),
                    recommendation=(
                        "Create integration test classes (e.g., "
                        + ", ".join(f"{n}IT.java" for n in untested_names[:3])
                        + ") with @SpringBootTest to exercise API endpoints. "
                        "Integration tests that produce OTel traces enable "
                        "Band 3 dynamic analysis."
                    ),
                    evidence_locator=first.locator,
                    collector_name=first.collector_name,
                    collector_version=first.collector_version,
                    confidence=0.75,
                    pattern_tag="otel-integration-test-coverage",
                )
            ],
        )


__all__ = ["OTelIntegrationTestCoverageRule"]
