# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

BASELINE_FORMAT_VERSION = 1


class NumericMetric(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    value: float
    unit: str = ""


class SetMetric(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    items: list[str] = Field(default_factory=list)

    @property
    def item_set(self) -> frozenset[str]:
        return frozenset(self.items)


class MetricCategory(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    category: str
    numeric_metrics: dict[str, NumericMetric] = Field(default_factory=dict)
    set_metrics: dict[str, SetMetric] = Field(default_factory=dict)


class StructuralBaseline(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = BASELINE_FORMAT_VERSION
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    source_repo: str = ""
    metrics: dict[str, MetricCategory] = Field(default_factory=dict)
