# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the OpenAPI collector.

Covers OpenAPI/Swagger specification analysis including endpoints,
HTTP methods, and operation metadata.
"""

from __future__ import annotations

from nfr_review.models import BasePayload

__all__ = [
    "OpenApiAnalysisPayload",
    "OpenApiEndpoint",
]


class OpenApiEndpoint(BasePayload):
    method: str
    path: str
    operation_id: str = ""
    summary: str = ""


class OpenApiAnalysisPayload(BasePayload):
    file_path: str
    openapi_version: str = ""
    title: str = ""
    endpoints: list[OpenApiEndpoint] = []
