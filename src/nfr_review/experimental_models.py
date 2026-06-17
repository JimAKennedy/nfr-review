# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Pydantic v2 data models for experimental class-focused reports."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from nfr_review.arch_models import C4Diagram


class CrossRepoEdge(BaseModel):
    """A relationship between classes in different repositories."""

    model_config = ConfigDict(extra="forbid")

    source_repo: str
    target_repo: str
    source_class: str
    target_class: str


class ExperimentalReport(BaseModel):
    """Root model for an experimental class-diagram-focused report."""

    model_config = ConfigDict(extra="forbid")

    repo_name: str
    class_diagrams: list[C4Diagram] = Field(default_factory=list)
    cross_repo_edges: list[CrossRepoEdge] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


__all__ = [
    "CrossRepoEdge",
    "ExperimentalReport",
]
