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

from nfr_review.models import Finding, _strip_line_from_locator


@dataclass
class BaselineData:
    """Parsed baseline: the set of identity keys from a prior run.

    Stores two key sets for backward-compatible matching:
    - ``legacy_keys``: 3-tuple ``(rule_id, evidence_locator, pattern_tag)``
    - ``stable_keys``: 4-tuple ``(rule_id, file_path, pattern_tag, content_hash)``
    """

    legacy_keys: set[tuple[str, str, str]] = field(default_factory=set)
    stable_keys: set[tuple[str, str, str, str]] = field(default_factory=set)
    run_metadata: dict[str, Any] = field(default_factory=dict)
    finding_count: int = 0

    @property
    def keys(self) -> set[tuple[str, str, str]]:
        """Backward-compatible alias — returns legacy keys."""
        return self.legacy_keys


def load_baseline(path: Path) -> BaselineData:
    """Load a prior JSONL file and extract finding identity keys."""
    if not path.exists():
        raise FileNotFoundError(f"baseline file not found: {path}")

    legacy_keys: set[tuple[str, str, str]] = set()
    stable_keys: set[tuple[str, str, str, str]] = set()
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
                content_hash = record.get("content_hash", "")
                if rule_id and locator is not None and tag is not None:
                    legacy_keys.add((rule_id, locator, tag))
                    finding_count += 1
                    if content_hash:
                        file_path = _strip_line_from_locator(locator)
                        stable_keys.add((rule_id, file_path, tag, content_hash))

    return BaselineData(
        legacy_keys=legacy_keys,
        stable_keys=stable_keys,
        run_metadata=run_metadata,
        finding_count=finding_count,
    )


def filter_new_findings(findings: list[Finding], baseline: BaselineData) -> list[Finding]:
    """Return only findings whose identity is NOT in the baseline.

    Uses dual-key matching: checks the stable (content-hash) key first,
    then falls back to the legacy (line-number) key.  A finding is
    considered known if *either* key matches.
    """
    new: list[Finding] = []
    for f in findings:
        if f.content_hash and f.stable_identity_key in baseline.stable_keys:
            continue
        if f.identity_key in baseline.legacy_keys:
            continue
        new.append(f)
    return new


__all__ = ["BaselineData", "filter_new_findings", "load_baseline"]
