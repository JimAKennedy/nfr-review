# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Interaction baseline model — capture and compare UAT-observed interactions.

A baseline is a versioned snapshot of interaction fingerprints extracted from
OTel traces collected during UAT.  It is saved as a JSON file and used by the
production monitor to flag novel interactions not seen in UAT.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from nfr_review.monitor.fingerprint import InteractionFingerprint

BASELINE_FORMAT_VERSION = 1


class InteractionBaseline(BaseModel):
    """Versioned snapshot of interaction fingerprints from a UAT trace capture."""

    model_config = ConfigDict(frozen=True)

    version: int = BASELINE_FORMAT_VERSION
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    source: str = ""
    trace_count: int = 0
    span_count: int = 0
    fingerprints: list[InteractionFingerprint] = Field(default_factory=list)

    @property
    def fingerprint_set(self) -> set[InteractionFingerprint]:
        return set(self.fingerprints)

    @property
    def fingerprint_hashes(self) -> set[str]:
        return {fp.fingerprint_hash for fp in self.fingerprints}


def save_baseline(baseline: InteractionBaseline, path: Path) -> None:
    """Write a baseline to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = baseline.model_dump(mode="json")
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_baseline(path: Path) -> InteractionBaseline:
    """Load a baseline from a JSON file.

    Raises FileNotFoundError if path does not exist.
    Raises ValueError if the baseline version is unsupported.
    """
    if not path.exists():
        raise FileNotFoundError(f"baseline file not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    version = data.get("version", 0)
    if version > BASELINE_FORMAT_VERSION:
        raise ValueError(
            f"unsupported baseline version {version} "
            f"(max supported: {BASELINE_FORMAT_VERSION})"
        )

    return InteractionBaseline.model_validate(data)


def diff_baselines(
    baseline: InteractionBaseline,
    observed: set[InteractionFingerprint],
) -> tuple[set[InteractionFingerprint], set[InteractionFingerprint]]:
    """Compare observed fingerprints against a baseline.

    Returns (novel, disappeared):
    - novel: fingerprints in observed but not in baseline
    - disappeared: fingerprints in baseline but not in observed
    """
    baseline_set = baseline.fingerprint_set
    novel = observed - baseline_set
    disappeared = baseline_set - observed
    return novel, disappeared


__all__ = [
    "BASELINE_FORMAT_VERSION",
    "InteractionBaseline",
    "diff_baselines",
    "load_baseline",
    "save_baseline",
]
