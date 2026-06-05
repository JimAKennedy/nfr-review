# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the CI artifact collector."""

from __future__ import annotations

from nfr_review.models import BasePayload


class CiPipelinePayload(BasePayload):
    """Payload for kind='ci-pipeline' evidence."""

    file_path: str
    ci_system: str
    has_test_step: bool
    has_security_scan: bool
    job_names: list[str]
    step_names: list[str]


class CmakeTestSignalFile(BasePayload):
    """One CMakeLists.txt with test framework signals."""

    file_path: str
    signals: list[str]


class CmakeTestSignalsPayload(BasePayload):
    """Payload for kind='cmake-test-signals' evidence."""

    files: list[CmakeTestSignalFile]
    has_test_framework: bool


class CiSummaryPayload(BasePayload):
    """Payload for kind='ci-summary' evidence."""

    total_pipelines: int
    ci_systems: list[str]
    any_test_step: bool
    any_security_scan: bool


__all__ = [
    "CiPipelinePayload",
    "CmakeTestSignalFile",
    "CmakeTestSignalsPayload",
    "CiSummaryPayload",
]
