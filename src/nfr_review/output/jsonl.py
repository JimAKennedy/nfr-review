# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""R018 JSONL writer.

The first line is always a ``run_metadata`` record carrying the full
provenance chain (R021); every subsequent line is a ``finding`` record. Each
line is independently parseable by ``json.loads``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nfr_review.models import Finding
from nfr_review.output._errors import OutputError

if TYPE_CHECKING:
    from nfr_review.engine import RunResult

_FINDING_FIELDS: tuple[str, ...] = tuple(Finding.model_fields.keys())


def _finding_record(finding: Finding) -> dict[str, Any]:
    return {"record_type": "finding", **finding.model_dump()}


def _skipped_record(rule_id: str, reason: str) -> dict[str, Any]:
    record: dict[str, Any] = {"record_type": "finding"}
    for field in _FINDING_FIELDS:
        record[field] = None
    record["rule_id"] = rule_id
    record["rag"] = "skipped"
    record["summary"] = f"rule skipped: {reason}"
    return record


def write_jsonl(run_result: RunResult, path: Path) -> None:
    """Write ``run_result`` to ``path`` as R018 JSONL.

    Order is fixed: run_metadata first, then findings, then synthetic skipped
    records — so a streaming reader can short-circuit on metadata before
    consuming findings.
    """
    if run_result.run_metadata is None:
        raise OutputError(f"cannot write JSONL to {path}: run_result.run_metadata is None")

    metadata_record: dict[str, Any] = {
        "record_type": "run_metadata",
        **run_result.run_metadata.model_dump(),
    }

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as fh:
            fh.write(json.dumps(metadata_record, ensure_ascii=False))
            fh.write("\n")
            for finding in run_result.findings:
                fh.write(json.dumps(_finding_record(finding), ensure_ascii=False))
                fh.write("\n")
            for rule_result in run_result.rule_results:
                if rule_result.skipped:
                    reason = rule_result.skip_reason or "rule reported skipped"
                    fh.write(
                        json.dumps(
                            _skipped_record(rule_result.rule_id, reason),
                            ensure_ascii=False,
                        )
                    )
                    fh.write("\n")
    except OSError as exc:
        raise OutputError(f"failed to write JSONL to {path}: {exc}") from exc


__all__ = ["write_jsonl"]
