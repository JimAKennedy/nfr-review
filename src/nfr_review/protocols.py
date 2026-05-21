# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from nfr_review.models import Evidence, RuleResult

Band = Literal[1, 2]


@runtime_checkable
class Collector(Protocol):
    """Pluggable evidence collector. Implementations gather raw signal from a target repo."""

    name: str
    version: str

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        """Walk repo_path and return a list of Evidence records."""
        ...


@runtime_checkable
class Rule(Protocol):
    """Pluggable NFR rule. Implementations evaluate evidence and emit a RuleResult."""

    id: str
    band: Band
    required_collectors: list[str]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        """Evaluate the supplied evidence and return a RuleResult."""
        ...


__all__ = ["Band", "Collector", "Rule"]
