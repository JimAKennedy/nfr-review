# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Baseline loading and diff-mode filtering for JSONL run records.

When ``--baseline`` is supplied on the CLI, prior findings are loaded from a
JSONL file and used to suppress known findings so the exit code reflects only
*new* regressions.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nfr_review.models import Finding, _strip_line_from_locator

# Graphify reassigns community IDs on every clustering run, so locators built
# from them (``community:91``, ``community-pair:2-3``) carry no identity across
# runs.  Findings with such locators are paired one-to-one per rule instead.
_UNSTABLE_LOCATOR_RE = re.compile(r"^(community|community-pair):")


@dataclass
class ShiftedFinding:
    """A finding that matches the baseline via content hash but at a different line."""

    finding: Finding
    baseline_locator: str


@dataclass
class FindingClassification:
    """Classified findings after comparing against a baseline.

    - ``new``: not present in the baseline at all
    - ``shifted``: same content at a different line number
    - ``resolved``: present in the baseline but absent from the current scan
    """

    new: list[Finding] = field(default_factory=list)
    shifted: list[ShiftedFinding] = field(default_factory=list)
    resolved: list[tuple[str, ...]] = field(default_factory=list)


@dataclass
class BaselineData:
    """Parsed baseline: the set of identity keys from a prior run.

    Stores two key sets for backward-compatible matching:
    - ``legacy_keys``: 3-tuple ``(rule_id, evidence_locator, pattern_tag)``
    - ``stable_keys``: 4-tuple ``(rule_id, file_path, pattern_tag, content_hash)``

    ``hashless_summaries`` maps the legacy key of each finding that has no
    content hash to its summary, so line shifts and renumbered communities can
    still be recognised.  Suppressed and resolved records are not loaded: they
    were not active findings in the baseline run.
    """

    legacy_keys: set[tuple[str, str, str]] = field(default_factory=set)
    stable_keys: set[tuple[str, str, str, str]] = field(default_factory=set)
    hashless_summaries: dict[tuple[str, str, str], str] = field(default_factory=dict)
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
    hashless_summaries: dict[tuple[str, str, str], str] = {}
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
                if (
                    record.get("suppressed") is True
                    or record.get("classification") == "resolved"
                ):
                    continue
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
                    else:
                        hashless_summaries[(rule_id, locator, tag)] = (
                            record.get("summary") or ""
                        )

    return BaselineData(
        legacy_keys=legacy_keys,
        stable_keys=stable_keys,
        hashless_summaries=hashless_summaries,
        run_metadata=run_metadata,
        finding_count=finding_count,
    )


def filter_new_findings(findings: list[Finding], baseline: BaselineData) -> list[Finding]:
    """Return only findings whose identity is NOT in the baseline.

    Equivalent to ``classify_findings(findings, baseline).new`` so the exit
    code and the PR comment always agree on what is new.
    """
    return classify_findings(findings, baseline).new


def _build_baseline_locator_index(
    baseline: BaselineData,
) -> dict[tuple[str, str, str, str], str]:
    """Map stable keys to their original evidence_locator (with line number).

    This requires re-parsing the baseline file — but BaselineData doesn't store
    the original locators alongside stable keys.  As a lightweight alternative,
    we reconstruct from legacy_keys: for each legacy key, look up matching
    stable keys via a pre-built index keyed by (rule_id, file_path, pattern_tag).
    """
    stable_by_prefix: dict[tuple[str, str, str], list[tuple[str, str, str, str]]] = {}
    for stable_key in baseline.stable_keys:
        s_rule, s_file, s_tag, _s_hash = stable_key
        stable_by_prefix.setdefault((s_rule, s_file, s_tag), []).append(stable_key)

    index: dict[tuple[str, str, str, str], str] = {}
    for legacy_key in baseline.legacy_keys:
        rule_id, locator, pattern_tag = legacy_key
        file_path = _strip_line_from_locator(locator)
        for stable_key in stable_by_prefix.get((rule_id, file_path, pattern_tag), ()):
            index[stable_key] = locator
    return index


def _locator_kind(locator: str) -> str | None:
    """Return the unstable-locator prefix (e.g. ``community``), or None."""
    match = _UNSTABLE_LOCATOR_RE.match(locator)
    return match.group(1) if match else None


def _match_hashless(
    unmatched: list[Finding],
    baseline: BaselineData,
    matched_legacy_keys: set[tuple[str, str, str]],
) -> tuple[list[Finding], list[ShiftedFinding]]:
    """Pair findings without a content hash to unmatched hashless baseline entries.

    Two passes, each consuming a baseline entry at most once:

    1. Same rule, pattern tag, file and summary at a different line.
    2. Unstable (community-ID) locators of the same kind, paired per rule.
    """
    available = [k for k in baseline.hashless_summaries if k not in matched_legacy_keys]
    still_new: list[Finding] = []
    shifted: list[ShiftedFinding] = []

    def take(predicate: Any) -> tuple[str, str, str] | None:
        for key in available:
            if predicate(key):
                available.remove(key)
                matched_legacy_keys.add(key)
                return key
        return None

    pending: list[Finding] = []
    for f in unmatched:
        if f.content_hash or _locator_kind(f.evidence_locator):
            pending.append(f)
            continue
        file_path = _strip_line_from_locator(f.evidence_locator)
        key = take(
            lambda k, f=f, file_path=file_path: (
                k[0] == f.rule_id
                and k[2] == f.pattern_tag
                and _locator_kind(k[1]) is None
                and _strip_line_from_locator(k[1]) == file_path
                and baseline.hashless_summaries[k] == f.summary
            )
        )
        if key is None:
            pending.append(f)
        else:
            shifted.append(ShiftedFinding(finding=f, baseline_locator=key[1]))

    for f in pending:
        kind = _locator_kind(f.evidence_locator)
        key = None
        if kind is not None and not f.content_hash:
            key = take(
                lambda k, f=f, kind=kind: (
                    k[0] == f.rule_id and k[2] == f.pattern_tag and _locator_kind(k[1]) == kind
                )
            )
        if key is None:
            still_new.append(f)
        else:
            shifted.append(ShiftedFinding(finding=f, baseline_locator=key[1]))

    return still_new, shifted


def classify_findings(
    findings: list[Finding], baseline: BaselineData
) -> FindingClassification:
    """Classify findings as new, shifted, or resolved relative to a baseline.

    - **new**: finding not in baseline by either stable or legacy key
    - **shifted**: finding matches via stable key (content hash) but NOT
      via legacy key (line number changed); or, for findings without a
      content hash, matches an unmatched baseline entry by file and summary,
      or by rule for community-ID locators (see ``_match_hashless``)
    - **resolved**: baseline entries not matched by any current finding

    ``filter_new_findings()`` remains the simpler backward-compatible API;
    this function provides richer information for PR comments.
    """
    matched_stable_keys: set[tuple[str, ...]] = set()
    matched_legacy_keys: set[tuple[str, str, str]] = set()
    locator_index = _build_baseline_locator_index(baseline)

    new_findings: list[Finding] = []
    shifted_findings: list[ShiftedFinding] = []

    for f in findings:
        stable_match = f.content_hash and f.stable_identity_key in baseline.stable_keys
        legacy_match = f.identity_key in baseline.legacy_keys

        if stable_match:
            matched_stable_keys.add(f.stable_identity_key)
        if legacy_match:
            matched_legacy_keys.add(f.identity_key)

        if stable_match and not legacy_match:
            bl_locator = locator_index.get(
                f.stable_identity_key,  # type: ignore[arg-type]
                "(unknown)",
            )
            shifted_findings.append(ShiftedFinding(finding=f, baseline_locator=bl_locator))
        elif not stable_match and not legacy_match:
            new_findings.append(f)

    new_findings, hashless_shifted = _match_hashless(
        new_findings, baseline, matched_legacy_keys
    )
    shifted_findings.extend(hashless_shifted)

    resolved: list[tuple[str, ...]] = []
    for stable_key in baseline.stable_keys:
        if stable_key not in matched_stable_keys:
            resolved.append(stable_key)
    for legacy_key in baseline.legacy_keys:
        if legacy_key not in matched_legacy_keys:
            file_path = _strip_line_from_locator(legacy_key[1])
            pseudo_stable = (legacy_key[0], file_path, legacy_key[2])
            already_resolved = any(
                r[0] == pseudo_stable[0]
                and r[1] == pseudo_stable[1]
                and r[2] == pseudo_stable[2]
                for r in resolved
                if len(r) >= 3
            )
            if not already_resolved:
                resolved.append(legacy_key)

    return FindingClassification(
        new=new_findings,
        shifted=shifted_findings,
        resolved=resolved,
    )


__all__ = [
    "BaselineData",
    "FindingClassification",
    "ShiftedFinding",
    "classify_findings",
    "filter_new_findings",
    "load_baseline",
]
