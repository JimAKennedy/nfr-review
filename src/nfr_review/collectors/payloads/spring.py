# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the Spring config collector."""

from __future__ import annotations

from typing import Any

from nfr_review.models import BasePayload


class SpringConfigFilePayload(BasePayload):
    """Payload for kind='spring-config-file' evidence."""

    file_path: str
    profile: str | None = None
    management: dict[str, Any]
    logging: dict[str, Any]
    server: dict[str, Any]
    spring_security: dict[str, Any]
    actuator: dict[str, Any]
    raw_keys: list[str]


__all__ = [
    "SpringConfigFilePayload",
]
