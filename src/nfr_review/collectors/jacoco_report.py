# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""JaCoCo report collector — parses JaCoCo XML coverage reports and emits
Evidence with per-package and overall coverage metrics.

Evidence payload contract (kind="jacoco-report"):
    report_path: str — path relative to repo_path
    report_name: str — name attribute from <report> element
    overall: dict — overall coverage percentages
        line_covered: int
        line_missed: int
        line_pct: float — line coverage percentage (0.0-100.0)
        branch_covered: int
        branch_missed: int
        branch_pct: float — branch coverage percentage (0.0-100.0)
        instruction_covered: int
        instruction_missed: int
        instruction_pct: float — instruction coverage percentage (0.0-100.0)
    packages: list[dict] — per-package coverage
        name: str
        line_pct: float
        branch_pct: float
        instruction_pct: float
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET  # nosec B405
from pathlib import Path
from typing import Any

from nfr_review.collectors.payloads.jacoco import (
    JacocoCoverageMetrics,
    JacocoPackageCoverage,
    JacocoReportPayload,
)
from nfr_review.models import Evidence
from nfr_review.registry import collector_registry

logger = logging.getLogger("nfr_review.collectors.jacoco_report")

_HIDDEN_DIRS = frozenset({".git", ".svn", ".hg", ".idea", ".vscode", "node_modules"})

# Patterns for locating JaCoCo XML reports
_JACOCO_PATTERNS = [
    "target/site/jacoco/jacoco.xml",
    "build/reports/jacoco/*/jacoco.xml",
    "target/site/jacoco-aggregate/jacoco.xml",
    "**/jacoco.xml",
]


def _is_hidden(rel: Path) -> bool:
    """Return True if any path component is a hidden dir or in _HIDDEN_DIRS."""
    return any(part.startswith(".") or part in _HIDDEN_DIRS for part in rel.parts)


def _pct(covered: int, missed: int) -> float:
    """Calculate coverage percentage from covered and missed counts."""
    total = covered + missed
    if total == 0:
        return 100.0
    return round(covered / total * 100.0, 2)


def _extract_counters(element: ET.Element) -> dict[str, dict[str, int]]:
    """Extract counter values from an XML element's <counter> children."""
    counters: dict[str, dict[str, int]] = {}
    for counter in element.findall("counter"):
        ctype = counter.get("type", "").upper()
        missed = int(counter.get("missed", "0"))
        covered = int(counter.get("covered", "0"))
        counters[ctype] = {"missed": missed, "covered": covered}
    return counters


def _coverage_from_counters(counters: dict[str, dict[str, int]]) -> JacocoCoverageMetrics:
    """Build coverage metrics from counter data."""
    line = counters.get("LINE", {"covered": 0, "missed": 0})
    branch = counters.get("BRANCH", {"covered": 0, "missed": 0})
    instruction = counters.get("INSTRUCTION", {"covered": 0, "missed": 0})

    return JacocoCoverageMetrics(
        line_covered=line["covered"],
        line_missed=line["missed"],
        line_pct=_pct(line["covered"], line["missed"]),
        branch_covered=branch["covered"],
        branch_missed=branch["missed"],
        branch_pct=_pct(branch["covered"], branch["missed"]),
        instruction_covered=instruction["covered"],
        instruction_missed=instruction["missed"],
        instruction_pct=_pct(instruction["covered"], instruction["missed"]),
    )


class JaCoCoReportCollector:
    name = "jacoco-report"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        evidence: list[Evidence] = []
        seen: set[Path] = set()

        for pattern in _JACOCO_PATTERNS:
            for xml_file in sorted(repo_path.glob(pattern)):
                if not xml_file.is_file():
                    continue

                resolved = xml_file.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)

                rel = xml_file.relative_to(repo_path)
                if _is_hidden(rel):
                    continue

                try:
                    raw = xml_file.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError) as exc:
                    logger.debug("Cannot read %s: %s", rel, exc)
                    continue

                try:
                    root = ET.fromstring(raw)  # nosec B314
                except ET.ParseError as exc:
                    logger.debug("XML parse error in %s: %s", rel, exc)
                    continue

                if root.tag != "report":
                    logger.debug("Unexpected root element %r in %s", root.tag, rel)
                    continue

                report_name = root.get("name", "unknown")

                # Extract overall counters from <report> level
                overall_counters = _extract_counters(root)
                overall = _coverage_from_counters(overall_counters)

                # Extract per-package coverage
                packages: list[JacocoPackageCoverage] = []
                for pkg in root.findall("package"):
                    pkg_name = pkg.get("name", "unknown")
                    pkg_counters = _extract_counters(pkg)
                    pkg_cov = _coverage_from_counters(pkg_counters)
                    packages.append(
                        JacocoPackageCoverage(
                            name=pkg_name,
                            line_pct=pkg_cov.line_pct,
                            branch_pct=pkg_cov.branch_pct,
                            instruction_pct=pkg_cov.instruction_pct,
                        )
                    )

                payload = JacocoReportPayload(
                    report_path=str(rel),
                    report_name=report_name,
                    overall=overall,
                    packages=packages,
                )

                evidence.append(
                    Evidence(
                        collector_name=self.name,
                        collector_version=self.version,
                        locator=str(rel),
                        kind="jacoco-report",
                        payload=payload,
                    )
                )

        return evidence


def _register() -> None:
    if "jacoco-report" not in collector_registry:
        collector_registry.register("jacoco-report", JaCoCoReportCollector())


_register()

__all__ = ["JaCoCoReportCollector"]
