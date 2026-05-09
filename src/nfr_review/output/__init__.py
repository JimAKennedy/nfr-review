"""Output formatters for nfr-review.

R007 CSV (10 fields, fixed order) and R018 JSONL (run_metadata + per-finding
records) are the canonical persistence formats. Both writers are defensive:
they create missing parent directories and surface filesystem errors as
``OutputError`` rather than letting the engine abort with a raw ``OSError``.
"""

from __future__ import annotations

from nfr_review.output._errors import OutputError
from nfr_review.output.classify import Region, classify_region, partition_findings
from nfr_review.output.csv import CSV_HEADER, write_csv
from nfr_review.output.jsonl import write_jsonl

__all__ = [
    "OutputError",
    "Region",
    "classify_region",
    "partition_findings",
    "CSV_HEADER",
    "write_csv",
    "write_jsonl",
]
