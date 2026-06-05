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
    from nfr_review.suppression import SuppressionInfo

_FINDING_FIELDS: tuple[str, ...] = tuple(Finding.model_fields.keys())


def _finding_record(finding: Finding, *, classification: str | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {"record_type": "finding", **finding.model_dump()}
    if classification is not None:
        record["classification"] = classification
    return record


def _skipped_record(rule_id: str, reason: str) -> dict[str, Any]:
    record: dict[str, Any] = {"record_type": "finding"}
    for field in _FINDING_FIELDS:
        record[field] = None
    record["rule_id"] = rule_id
    record["rag"] = "skipped"
    record["summary"] = f"rule skipped: {reason}"
    return record


def write_jsonl(
    run_result: RunResult,
    path: Path,
    *,
    classification: object | None = None,
    suppressed_findings: list[tuple[Finding, SuppressionInfo]] | None = None,
) -> None:
    """Write ``run_result`` to ``path`` as R018 JSONL.

    Order is fixed: run_metadata first, then findings, then synthetic skipped
    records — so a streaming reader can short-circuit on metadata before
    consuming findings.

    When ``classification`` is provided (a ``FindingClassification`` from
    ``baseline.py``), findings are tagged with ``classification: "new"`` and
    shifted/resolved entries are appended as additional records.

    When ``suppressed_findings`` is provided (a list of
    ``(Finding, SuppressionInfo)`` tuples), they are emitted with
    ``suppressed: true`` plus audit metadata (reason, source) for
    downstream auditing.
    """
    if run_result.run_metadata is None:
        raise OutputError(f"cannot write JSONL to {path}: run_result.run_metadata is None")

    metadata_record: dict[str, Any] = {
        "record_type": "run_metadata",
        **run_result.run_metadata.model_dump(),
    }
    if suppressed_findings:
        metadata_record["suppressed_count"] = len(suppressed_findings)
        metadata_record["suppressed_with_reason_count"] = sum(
            1 for _, info in suppressed_findings if info.reason
        )
        metadata_record["suppressed_without_reason_count"] = sum(
            1 for _, info in suppressed_findings if not info.reason
        )

    new_finding_keys: set[tuple[str, ...]] | None = None
    shifted_map: dict[tuple[str, ...], str] | None = None
    if classification is not None:
        from nfr_review.baseline import FindingClassification

        if isinstance(classification, FindingClassification):
            new_finding_keys = {f.identity_key for f in classification.new}
            shifted_map = {
                sf.finding.identity_key: sf.baseline_locator for sf in classification.shifted
            }

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as fh:
            fh.write(json.dumps(metadata_record, ensure_ascii=False))
            fh.write("\n")

            for finding in run_result.findings:
                cls_tag: str | None = None
                extra: dict[str, Any] = {}
                if new_finding_keys is not None:
                    if finding.identity_key in new_finding_keys:
                        cls_tag = "new"
                    elif shifted_map and finding.identity_key in shifted_map:
                        cls_tag = "shifted"
                        extra["baseline_locator"] = shifted_map[finding.identity_key]
                    else:
                        cls_tag = "baseline"
                record = _finding_record(finding, classification=cls_tag)
                record.update(extra)
                fh.write(json.dumps(record, ensure_ascii=False))
                fh.write("\n")

            if classification is not None:
                from nfr_review.baseline import FindingClassification

                if isinstance(classification, FindingClassification):
                    for resolved_key in classification.resolved:
                        resolved_record: dict[str, Any] = {
                            "record_type": "finding",
                            "classification": "resolved",
                            "rule_id": resolved_key[0] if len(resolved_key) > 0 else "",
                            "evidence_locator": (
                                resolved_key[1] if len(resolved_key) > 1 else ""
                            ),
                            "pattern_tag": resolved_key[2] if len(resolved_key) > 2 else "",
                        }
                        fh.write(json.dumps(resolved_record, ensure_ascii=False))
                        fh.write("\n")

            if suppressed_findings:
                for sf, si in suppressed_findings:
                    record = _finding_record(sf)
                    record["suppressed"] = True
                    record["suppression_reason"] = si.reason
                    record["suppression_source"] = f"{si.source_file}:{si.source_line}"
                    fh.write(json.dumps(record, ensure_ascii=False))
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
