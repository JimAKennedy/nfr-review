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

CSV_HEADER: tuple[str, ...] = tuple(Finding.model_fields.keys())


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


def write_csv(run_result: RunResult, path: Path) -> None:
    """Write ``run_result`` to ``path`` as R007 CSV.

    Creates parent directories as needed. Wraps filesystem errors in
    ``OutputError`` so the CLI surfaces a clean message instead of a traceback.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh, quoting=csv.QUOTE_MINIMAL)
            writer.writerow(CSV_HEADER)
            for finding in run_result.findings:
                writer.writerow(_finding_row(finding))
            for rule_result in run_result.rule_results:
                if rule_result.skipped:
                    reason = rule_result.skip_reason or "rule reported skipped"
                    writer.writerow(_skipped_row(rule_result.rule_id, reason))
    except OSError as exc:
        raise OutputError(f"failed to write CSV to {path}: {exc}") from exc


__all__ = ["CSV_HEADER", "write_csv"]
