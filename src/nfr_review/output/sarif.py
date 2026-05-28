# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""SARIF 2.1.0 writer.

Produces a valid SARIF 2.1.0 JSON file from a ``RunResult``. Each Finding
becomes a ``result`` entry with severity-mapped levels and parsed evidence
locators. Skipped rules are emitted as ``notApplicable`` results with
suppressions.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nfr_review.output._errors import OutputError

if TYPE_CHECKING:
    from nfr_review.engine import RunResult
    from nfr_review.models import Finding, Severity

_SARIF_SCHEMA = (
    "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/"
    "main/sarif-2.1/schema/sarif-schema-2.1.0.json"
)

_SEVERITY_TO_LEVEL: dict[str, str] = {
    "critical": "error",
    "high": "error",
    "medium": "warning",
    "low": "note",
    "info": "note",
}

# Matches file://path, file://path:line, file://path:line:col
_FILE_LOCATOR_RE = re.compile(r"^file://(.+?)(?::(\d+)(?::(\d+))?)?$")


def _map_severity(severity: Severity) -> str:
    """Map nfr-review severity to SARIF level."""
    return _SEVERITY_TO_LEVEL.get(severity, "note")


_FALLBACK_LOCATION: dict[str, Any] = {"physicalLocation": {"artifactLocation": {"uri": "."}}}


def _parse_location(evidence_locator: str) -> dict[str, Any]:
    """Parse an evidence_locator into a SARIF location object.

    GitHub Code Scanning requires every result to have at least one location
    with a ``file``-scheme URI. Non-file locators (``dep:``, ``maven:``, etc.)
    fall back to the repo root.
    """
    m = _FILE_LOCATOR_RE.match(evidence_locator)
    if not m:
        return _FALLBACK_LOCATION
    uri = m.group(1)
    line = m.group(2)
    col = m.group(3)
    phys: dict[str, Any] = {
        "artifactLocation": {"uri": uri},
    }
    if line is not None:
        region: dict[str, int] = {"startLine": int(line)}
        if col is not None:
            region["startColumn"] = int(col)
        phys["region"] = region
    return {"physicalLocation": phys}


def _build_rules(findings: list[Finding]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Build deduplicated rules array and rule_id-to-index mapping."""
    rules: list[dict[str, Any]] = []
    index_map: dict[str, int] = {}
    for finding in findings:
        if finding.rule_id not in index_map:
            index_map[finding.rule_id] = len(rules)
            rules.append(
                {
                    "id": finding.rule_id,
                    "shortDescription": {"text": finding.summary},
                }
            )
    return rules, index_map


def _finding_to_result(
    finding: Finding,
    rule_index_map: dict[str, int],
) -> dict[str, Any]:
    """Convert a Finding to a SARIF result object."""
    text = f"{finding.summary}\nRecommendation: {finding.recommendation}"
    return {
        "ruleId": finding.rule_id,
        "ruleIndex": rule_index_map[finding.rule_id],
        "level": _map_severity(finding.severity),
        "message": {"text": text},
        "locations": [_parse_location(finding.evidence_locator)],
    }


def _skipped_to_result(rule_id: str, skip_reason: str | None) -> dict[str, Any]:
    """Convert a skipped rule to a SARIF notApplicable result."""
    justification = skip_reason or "rule reported skipped"
    return {
        "ruleId": rule_id,
        "kind": "notApplicable",
        "level": "none",
        "message": {"text": f"rule skipped: {justification}"},
        "locations": [_FALLBACK_LOCATION],
        "suppressions": [
            {
                "kind": "inSource",
                "justification": justification,
            }
        ],
    }


def write_sarif(run_result: RunResult, path: Path) -> None:
    """Write ``run_result`` to ``path`` as SARIF 2.1.0 JSON.

    Raises ``OutputError`` if ``run_metadata`` is ``None`` or if the file
    cannot be written.
    """
    if run_result.run_metadata is None:
        raise OutputError(f"cannot write SARIF to {path}: run_result.run_metadata is None")

    metadata = run_result.run_metadata
    rules, rule_index_map = _build_rules(run_result.findings)

    results: list[dict[str, Any]] = []
    for finding in run_result.findings:
        results.append(_finding_to_result(finding, rule_index_map))

    for rule_result in run_result.rule_results:
        if rule_result.skipped:
            results.append(_skipped_to_result(rule_result.rule_id, rule_result.skip_reason))

    sarif: dict[str, Any] = {
        "$schema": _SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "nfr-review",
                        "version": metadata.tool_version,
                        "rules": rules,
                    },
                },
                "results": results,
            }
        ],
    }

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(sarif, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        raise OutputError(f"failed to write SARIF to {path}: {exc}") from exc


__all__ = ["write_sarif"]
