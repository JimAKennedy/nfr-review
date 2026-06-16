# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: dockerfile-secret-leakage — flags potential secrets copied or set in Dockerfiles."""

from __future__ import annotations

import re
from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

_SECRET_FILE_PATTERNS = [
    re.compile(r"\.env$", re.IGNORECASE),
    re.compile(r"\.pem$", re.IGNORECASE),
    re.compile(r"\.key$", re.IGNORECASE),
    re.compile(r"id_rsa", re.IGNORECASE),
    re.compile(r"id_ed25519", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"credential", re.IGNORECASE),
    re.compile(r"password", re.IGNORECASE),
]

_SECRET_ENV_PATTERNS = [
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"key", re.IGNORECASE),
    re.compile(r"credential", re.IGNORECASE),
]

_ENV_FALSE_POSITIVES = frozenset(
    {
        "key_separator",
        "keyboard",
        "keyring",
        "keynote",
        "primary_key",
        "foreign_key",
        "sort_key",
    }
)


def _matches_secret_file(filename: str) -> bool:
    return any(pat.search(filename) for pat in _SECRET_FILE_PATTERNS)


def _matches_secret_env(name: str) -> bool:
    lower = name.lower()
    if lower in _ENV_FALSE_POSITIVES:
        return False
    return any(pat.search(name) for pat in _SECRET_ENV_PATTERNS)


class DockerfileSecretLeakageRule:
    """Flag Dockerfiles that COPY/ADD secret files or expose secrets via ARG/ENV."""

    id = "dockerfile-secret-leakage"
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

            for cmd in ev.payload.copy_add_commands:
                line = cmd.get("line", 0)
                instruction = cmd.get("instruction", "COPY")
                for src in cmd.get("sources", []):
                    if _matches_secret_file(src):
                        findings.append(
                            Finding(
                                rule_id=self.id,
                                rag="red",
                                severity="critical",
                                summary=(
                                    f"{instruction} of suspected secret file"
                                    f" '{src}' in {file_path}:{line}."
                                ),
                                recommendation=(
                                    "Use Docker BuildKit secrets"
                                    " (--mount=type=secret) instead of"
                                    f" {instruction} for sensitive files."
                                ),
                                evidence_locator=f"{file_path}:{line}",
                                collector_name=ev.collector_name,
                                collector_version=ev.collector_version,
                                confidence=0.8,
                                pattern_tag="dockerfile-secret-leakage",
                            )
                        )

            for entry in ev.payload.env_args:
                name = entry.get("name", "")
                line = entry.get("line", 0)
                instruction = entry.get("instruction", "ARG")
                if _matches_secret_env(name):
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="red",
                            severity="critical",
                            summary=(
                                f"{instruction} '{name}' in"
                                f" {file_path}:{line} may expose a secret"
                                " in the image layer."
                            ),
                            recommendation=(
                                "Use Docker BuildKit secrets or runtime"
                                " environment injection instead of baking"
                                " secrets into the image via"
                                f" {instruction}."
                            ),
                            evidence_locator=f"{file_path}:{line}",
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.8,
                            pattern_tag="dockerfile-secret-leakage",
                        )
                    )

        if not findings:
            first = df_evidence[0]
            findings.append(
                make_green_finding(
                    self.id,
                    "dockerfile-secret-leakage",
                    first,
                    summary="No potential secret leakage detected in Dockerfiles.",
                    confidence=0.8,
                    evidence_locator="all-dockerfiles",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "dockerfile-secret-leakage" not in rule_registry:
        rule_registry.register("dockerfile-secret-leakage", DockerfileSecretLeakageRule())


_register()

__all__ = ["DockerfileSecretLeakageRule"]
