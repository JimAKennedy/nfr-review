# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Pydantic v2 data models for experimental class-focused reports.

.. deprecated::
    The ``experimental`` command is deprecated in favour of ``arch``.
    Models have moved to :mod:`nfr_review.arch_models`.  This module
    re-exports them for backward compatibility.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from nfr_review.arch_models import (
    C4Diagram,
    CrossRepoEdge,
    DynamicAnalysisSection,
)


class ExperimentalReport(BaseModel):
    """Root model for an experimental class-diagram-focused report."""

    model_config = ConfigDict(extra="forbid")

    repo_name: str
    class_diagrams: list[C4Diagram] = Field(default_factory=list)
    cross_repo_edges: list[CrossRepoEdge] = Field(default_factory=list)
    dynamic_analysis: DynamicAnalysisSection | None = None
    metadata: dict = Field(default_factory=dict)


__all__ = [
    "CrossRepoEdge",
    "DynamicAnalysisSection",
    "ExperimentalReport",
]
