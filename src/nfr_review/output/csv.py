# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""R007 CSV writer.

Emits the 10 R007 fields in the canonical order (locked by
``Finding.model_fields``). One row per real finding, plus one synthetic
``rag='skipped'`` row per skipped rule so every rule the engine considered is
visible in the on-disk artifact.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import TYPE_CHECKING

from nfr_review.models import Finding
from nfr_review.output._errors import OutputError

if TYPE_CHECKING:
    from nfr_review.engine import RunResult
    from nfr_review.suppression import SuppressionInfo

CSV_HEADER: tuple[str, ...] = tuple(Finding.model_fields.keys())
CSV_HEADER_WITH_AUDIT: tuple[str, ...] = (*CSV_HEADER, "suppression_reason")


def _finding_row(finding: Finding) -> list[str]:
    dumped = finding.model_dump()
    return [_stringify(dumped[col]) for col in CSV_HEADER]


def _skipped_row(rule_id: str, reason: str) -> list[str]:
    return [
        rule_id,
        "skipped",
        "",
        f"rule skipped: {reason}",
        "",
        "",
        "",
        "",
        "",
        "",
    ]


def _stringify(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def write_csv(
    run_result: RunResult,
    path: Path,
    *,
    suppressed_findings: list[tuple[Finding, SuppressionInfo]] | None = None,
) -> None:
    """Write ``run_result`` to ``path`` as R007 CSV.

    Creates parent directories as needed. When ``suppressed_findings``
    is provided, appends suppressed rows with ``rag='suppressed'`` and
    an extra ``suppression_reason`` column.  The header is extended to
    include this column whenever suppressed findings are present.

    Wraps filesystem errors in ``OutputError`` so the CLI surfaces a
    clean message instead of a traceback.
    """
    has_suppressed = bool(suppressed_findings)
    header = CSV_HEADER_WITH_AUDIT if has_suppressed else CSV_HEADER
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh, quoting=csv.QUOTE_MINIMAL)
            writer.writerow(header)
            for finding in run_result.findings:
                row = _finding_row(finding)
                if has_suppressed:
                    row.append("")
                writer.writerow(row)
            if suppressed_findings:
                for sf, si in suppressed_findings:
                    row = _finding_row(sf)
                    row[1] = "suppressed"  # override rag column
                    row.append(si.reason or "")
                    writer.writerow(row)
            for rule_result in run_result.rule_results:
                if rule_result.skipped:
                    reason = rule_result.skip_reason or "rule reported skipped"
                    row = _skipped_row(rule_result.rule_id, reason)
                    if has_suppressed:
                        row.append("")
                    writer.writerow(row)
    except OSError as exc:
        raise OutputError(f"failed to write CSV to {path}: {exc}") from exc


__all__ = ["CSV_HEADER", "CSV_HEADER_WITH_AUDIT", "write_csv"]
