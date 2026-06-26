# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: dockerfile-secret-leakage -- flags potential secrets copied or set in Dockerfiles."""

from __future__ import annotations

import re
from collections.abc import Iterable

from nfr_review.collectors.payloads.dockerfile import DockerfileAnalysisPayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit

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


class DockerfileSecretLeakageRule(FieldRule[DockerfileAnalysisPayload]):
    """Flag Dockerfiles that COPY/ADD secret files or expose secrets via ARG/ENV."""

    id = "dockerfile-secret-leakage"
    collector_name = "dockerfile"
    evidence_kind = "dockerfile-analysis"
    payload_type = DockerfileAnalysisPayload
    pattern_tag = "dockerfile-secret-leakage"
    required_tech: list[str] = ["dockerfile"]
    default_confidence = 0.8
    all_clear_summary = "No potential secret leakage detected in Dockerfiles."
    all_clear_recommendation = "No action required."

    def check(self, payload: DockerfileAnalysisPayload, ev: Evidence) -> Iterable[Hit]:
        for cmd in payload.copy_add_commands:
            for src in cmd.sources:
                if _matches_secret_file(src):
                    yield Hit(
                        rag="red",
                        severity="critical",
                        summary=(
                            f"{cmd.instruction} of suspected secret file"
                            f" '{src}' in {payload.file_path}:{cmd.line}."
                        ),
                        recommendation=(
                            "Use Docker BuildKit secrets"
                            " (--mount=type=secret) instead of"
                            f" {cmd.instruction} for sensitive files."
                        ),
                        locator=f"{payload.file_path}:{cmd.line}",
                    )

        for entry in payload.env_args:
            if _matches_secret_env(entry.name):
                yield Hit(
                    rag="red",
                    severity="critical",
                    summary=(
                        f"{entry.instruction} '{entry.name}' in"
                        f" {payload.file_path}:{entry.line} may expose a secret"
                        " in the image layer."
                    ),
                    recommendation=(
                        "Use Docker BuildKit secrets or runtime"
                        " environment injection instead of baking"
                        " secrets into the image via"
                        f" {entry.instruction}."
                    ),
                    locator=f"{payload.file_path}:{entry.line}",
                )


__all__ = ["DockerfileSecretLeakageRule"]
