# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Code debt marker collector — scans source files for TODO/FIXME/HACK markers."""

from __future__ import annotations

import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any

from nfr_review.collectors.payloads.code_debt import CodeDebtFileEntry, CodeDebtPayload
from nfr_review.hygiene import hygiene_collector_registry
from nfr_review.models import Evidence
from nfr_review.path_filter import iter_repo_files

logger = logging.getLogger(__name__)

_MARKERS = ("TODO", "FIXME", "HACK", "XXX", "TEMP", "WORKAROUND")
_MARKER_RE = re.compile(
    r"\b(" + "|".join(_MARKERS) + r")\b",
    re.IGNORECASE,
)


_SOURCE_SUFFIXES = frozenset(
    {
        ".py",
        ".java",
        ".go",
        ".rs",
        ".cs",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".rb",
        ".php",
        ".swift",
        ".kt",
        ".kts",
        ".scala",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".sh",
        ".bash",
        ".zsh",
        ".yaml",
        ".yml",
        ".toml",
        ".xml",
        ".gradle",
        ".tf",
        ".hcl",
    }
)


def _scan_file(path: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return counts
    for match in _MARKER_RE.finditer(text):
        counts[match.group(1).upper()] += 1
    return counts


class CodeDebtCollector:
    name = "code-debt"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        total = 0
        per_marker: Counter[str] = Counter()
        file_counts: list[CodeDebtFileEntry] = []

        for path in iter_repo_files(repo_path):
            if path.suffix not in _SOURCE_SUFFIXES:
                continue

            rel = path.relative_to(repo_path)

            counts = _scan_file(path)
            if counts:
                file_total = sum(counts.values())
                total += file_total
                per_marker += counts
                file_counts.append(
                    CodeDebtFileEntry(path=str(rel), count=file_total, markers=dict(counts))
                )

        file_counts.sort(key=lambda f: f.count, reverse=True)

        payload = CodeDebtPayload(
            total_markers=total,
            per_marker=dict(per_marker),
            file_count=len(file_counts),
            top_files=file_counts[:10],
        )

        return [
            Evidence(
                collector_name=self.name,
                collector_version=self.version,
                locator=".",
                kind="code-debt-analysis",
                payload=payload,
            )
        ]


def _register() -> None:
    if "code-debt" not in hygiene_collector_registry:
        hygiene_collector_registry.register("code-debt", CodeDebtCollector())


_register()

__all__ = ["CodeDebtCollector"]
