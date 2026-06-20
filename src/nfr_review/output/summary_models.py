# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Pydantic models for the LLM-generated executive summary."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RemediationItem(BaseModel):
    """A single remediation action with urgency ranking."""

    model_config = ConfigDict(extra="forbid")

    title: str
    urgency: Literal["immediate", "short-term", "medium-term"]
    description: str


class CouplingHotspot(BaseModel):
    """A pair of components or communities with disproportionate coupling."""

    model_config = ConfigDict(extra="forbid")

    component_a: str
    component_b: str
    description: str


class ExecSummary(BaseModel):
    """Structured executive summary produced by LLM summarization."""

    model_config = ConfigDict(extra="forbid")

    verdict: Literal["fit", "conditional", "unfit"]
    verdict_explanation: str
    risk_highlights: list[str] = Field(default_factory=list)
    remediation_priorities: list[RemediationItem] = Field(default_factory=list)
    production_risks: str
    open_source_readiness: str
    overall_score: int = Field(ge=0, le=100)
    structural_risks: list[str] = Field(default_factory=list)
    coupling_hotspots: list[CouplingHotspot] = Field(default_factory=list)


__all__ = ["CouplingHotspot", "ExecSummary", "RemediationItem"]
