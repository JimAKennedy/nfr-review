# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Baseline loading and diff-mode filtering for JSONL run records.

When ``--baseline`` is supplied on the CLI, prior findings are loaded from a
JSONL file and used to suppress known findings so the exit code reflects only
*new* regressions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nfr_review.models import Finding


@dataclass
class BaselineData:
    """Parsed baseline: the set of identity keys from a prior run."""

    keys: set[tuple[str, str, str]] = field(default_factory=set)
    run_metadata: dict[str, Any] = field(default_factory=dict)
    finding_count: int = 0


def load_baseline(path: Path) -> BaselineData:
    """Load a prior JSONL file and extract finding identity keys."""
    if not path.exists():
        raise FileNotFoundError(f"baseline file not found: {path}")

    keys: set[tuple[str, str, str]] = set()
    run_metadata: dict[str, Any] = {}
    finding_count = 0

    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            record_type = record.get("record_type")
            if record_type == "run_metadata":
                run_metadata = record
            elif record_type == "finding":
                rule_id = record.get("rule_id")
                locator = record.get("evidence_locator")
                tag = record.get("pattern_tag")
                if rule_id and locator is not None and tag is not None:
                    keys.add((rule_id, locator, tag))
                    finding_count += 1

    return BaselineData(keys=keys, run_metadata=run_metadata, finding_count=finding_count)


def filter_new_findings(findings: list[Finding], baseline: BaselineData) -> list[Finding]:
    """Return only findings whose identity_key is NOT in the baseline."""
    return [f for f in findings if f.identity_key not in baseline.keys]


__all__ = ["BaselineData", "filter_new_findings", "load_baseline"]
