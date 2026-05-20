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


__all__ = ["ExecSummary", "RemediationItem"]
