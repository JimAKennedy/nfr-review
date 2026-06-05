# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the ci-automation hygiene collector."""

from __future__ import annotations

from pydantic import ConfigDict

from nfr_review.models import BasePayload

__all__ = [
    "CiAutomationPayload",
    "CiConfigEntry",
]


class CiConfigEntry(BasePayload):
    model_config = ConfigDict(extra="allow")

    path: str
    provider: str
    raw_content_length: int
    jobs: list[str] = []
    steps: list[str] = []
    has_content: bool | None = None
    raw_keys: list[str] | None = None


class CiAutomationPayload(BasePayload):
    ci_systems: list[str]
    configs: list[CiConfigEntry]
    has_ci: bool
