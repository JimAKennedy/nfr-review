# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""HYG-LIC-004: SPDX license expression validation.

Reads the license field from pyproject.toml, package.json, and pom.xml
and validates against SPDX license identifiers.  Does NOT depend on
scancode — reads metadata files directly.
"""

from __future__ import annotations

import json
import logging
import re
import tomllib
from pathlib import Path
from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band

logger = logging.getLogger(__name__)

_VALID_SPDX = frozenset(
    {
        "0BSD",
        "AAL",
        "AFL-3.0",
        "AGPL-1.0-only",
        "AGPL-1.0-or-later",
        "AGPL-3.0-only",
        "AGPL-3.0-or-later",
        "Apache-1.0",
        "Apache-1.1",
        "Apache-2.0",
        "APSL-1.0",
        "APSL-1.1",
        "APSL-2.0",
        "Artistic-1.0",
        "Artistic-2.0",
        "BlueOak-1.0.0",
        "BSD-1-Clause",
        "BSD-2-Clause",
        "BSD-2-Clause-Patent",
        "BSD-3-Clause",
        "BSD-3-Clause-LBNL",
        "BSL-1.0",
        "CAL-1.0",
        "CAL-1.0-Combined-Work-Exception",
        "CDDL-1.0",
        "CECILL-2.1",
        "CPAL-1.0",
        "CUA-OPL-1.0",
        "ECL-1.0",
        "ECL-2.0",
        "EFL-1.0",
        "EFL-2.0",
        "Entessa",
        "EPL-1.0",
        "EPL-2.0",
        "EUDatagrid",
        "EUPL-1.1",
        "EUPL-1.2",
        "Fair",
        "Frameworx-1.0",
        "FSFAP",
        "FTLL",
        "GPL-2.0-only",
        "GPL-2.0-or-later",
        "GPL-3.0-only",
        "GPL-3.0-or-later",
        "HPND",
        "Intel",
        "IPA",
        "IPL-1.0",
        "ISC",
        "JSON",
        "LAL-1.2",
        "LAL-1.3",
        "Libpng",
        "LiLiQ-P-1.1",
        "LiLiQ-R-1.1",
        "LiLiQ-Rplus-1.1",
        "LPL-1.0",
        "LPL-1.02",
        "LPPL-1.0",
        "LPPL-1.1",
        "LPPL-1.2",
        "LPPL-1.3a",
        "LPPL-1.3c",
        "LGPL-2.0-only",
        "LGPL-2.0-or-later",
        "LGPL-2.1-only",
        "LGPL-2.1-or-later",
        "LGPL-3.0-only",
        "LGPL-3.0-or-later",
        "MIT",
        "MIT-0",
        "MPL-1.0",
        "MPL-1.1",
        "MPL-2.0",
        "MPL-2.0-no-copyleft-exception",
        "MS-PL",
        "MS-RL",
        "MulanPSL-2.0",
        "Multics",
        "NASA-1.3",
        "NCSA",
        "NGPL",
        "Nokia",
        "NPOSL-3.0",
        "NTP",
        "OCLC-2.0",
        "OFL-1.0",
        "OFL-1.1",
        "OFL-1.1-RFN",
        "OFL-1.1-no-RFN",
        "OGTSL",
        "OLDAP-2.8",
        "OSET-PL-2.1",
        "OSL-1.0",
        "OSL-1.1",
        "OSL-2.0",
        "OSL-2.1",
        "OSL-3.0",
        "PHP-3.0",
        "PHP-3.01",
        "PostgreSQL",
        "PSF-2.0",
        "QPL-1.0",
        "RPL-1.1",
        "RPL-1.5",
        "RPSL-1.0",
        "RSCPL",
        "SimPL-2.0",
        "SISSL",
        "Sleepycat",
        "SPL-1.0",
        "UCL-1.0",
        "Unicode-DFS-2016",
        "Unlicense",
        "UPL-1.0",
        "VSL-1.0",
        "W3C",
        "Watcom-1.0",
        "Xnet",
        "Zlib",
        "ZPL-2.0",
        "ZPL-2.1",
    }
)

_DEPRECATED_SPDX = frozenset(
    {
        "AGPL-1.0",
        "AGPL-3.0",
        "GPL-2.0",
        "GPL-2.0+",
        "GPL-3.0",
        "GPL-3.0+",
        "LGPL-2.0",
        "LGPL-2.0+",
        "LGPL-2.1",
        "LGPL-2.1+",
        "LGPL-3.0",
        "LGPL-3.0+",
        "BSD-2-Clause-FreeBSD",
        "BSD-2-Clause-NetBSD",
    }
)

_SPDX_OPERATORS = re.compile(r"\b(AND|OR|WITH)\b")

_COMMON_NAME_MAP: dict[str, str] = {
    "mit license": "MIT",
    "the mit license": "MIT",
    "the mit license (mit)": "MIT",
    "apache license 2.0": "Apache-2.0",
    "apache license, version 2.0": "Apache-2.0",
    "the apache software license, version 2.0": "Apache-2.0",
    "the apache license, version 2.0": "Apache-2.0",
    "bsd license": "BSD-3-Clause",
    "bsd 2-clause license": "BSD-2-Clause",
    "bsd 3-clause license": "BSD-3-Clause",
    "the 2-clause bsd license": "BSD-2-Clause",
    "the 3-clause bsd license": "BSD-3-Clause",
    "isc license": "ISC",
    "mozilla public license 2.0": "MPL-2.0",
    "mozilla public license, version 2.0": "MPL-2.0",
    "eclipse public license 1.0": "EPL-1.0",
    "eclipse public license - v 1.0": "EPL-1.0",
    "eclipse public license 2.0": "EPL-2.0",
    "eclipse public license - v 2.0": "EPL-2.0",
    "common development and distribution license 1.0": "CDDL-1.0",
    "gnu general public license v2.0 only": "GPL-2.0-only",
    "gnu general public license v3.0 only": "GPL-3.0-only",
    "gnu lesser general public license v2.1 only": "LGPL-2.1-only",
    "gnu lesser general public license v3.0 only": "LGPL-3.0-only",
    "the unlicense": "Unlicense",
    "public domain": "Unlicense",
}


def _normalize_license_name(raw: str) -> str:
    mapped = _COMMON_NAME_MAP.get(raw.strip().lower())
    return mapped if mapped else raw


def _extract_identifiers(expression: str) -> list[str]:
    expression = _normalize_license_name(expression)
    cleaned = expression.replace("(", " ").replace(")", " ")
    tokens = _SPDX_OPERATORS.split(cleaned)
    ids = []
    for token in tokens:
        token = token.strip()
        if token and token not in ("AND", "OR", "WITH"):
            if token.endswith("+"):
                token = token[:-1]
            ids.append(token)
    return ids


class SpdxValidationRule:
    id = "HYG-LIC-004"
    band: Band = 1
    required_collectors: list[str] = []
    category = "license"

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        repo_path = self._resolve_repo_path(context)
        if repo_path is None:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no target repo path available",
            )

        expressions = self._collect_license_expressions(repo_path)
        if not expressions:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no project metadata files with license field found",
            )

        findings: list[Finding] = []
        for source_file, expr in expressions:
            ids = _extract_identifiers(expr)
            invalid = [i for i in ids if i not in _VALID_SPDX and i not in _DEPRECATED_SPDX]
            deprecated = [i for i in ids if i in _DEPRECATED_SPDX]

            if invalid:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="red",
                        severity="high",
                        summary=(
                            f"Invalid SPDX identifier(s) in {source_file}: "
                            f"{', '.join(invalid)}"
                        ),
                        recommendation=(
                            "Use a valid SPDX license identifier from "
                            "https://spdx.org/licenses/"
                        ),
                        evidence_locator=source_file,
                        collector_name="spdx-validation",
                        collector_version="0.1.0",
                        confidence=0.95,
                        pattern_tag="spdx-validation",
                    )
                )
            elif deprecated:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=(
                            f"Deprecated SPDX identifier(s) in {source_file}: "
                            f"{', '.join(deprecated)}"
                        ),
                        recommendation=(
                            "Update to the current SPDX identifier form "
                            "(e.g., GPL-3.0 → GPL-3.0-only)."
                        ),
                        evidence_locator=source_file,
                        collector_name="spdx-validation",
                        collector_version="0.1.0",
                        confidence=0.9,
                        pattern_tag="spdx-validation",
                    )
                )
            else:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="green",
                        severity="info",
                        summary=f"Valid SPDX expression in {source_file}: {expr}",
                        recommendation="No action required.",
                        evidence_locator=source_file,
                        collector_name="spdx-validation",
                        collector_version="0.1.0",
                        confidence=0.95,
                        pattern_tag="spdx-validation",
                    )
                )

        return RuleResult(rule_id=self.id, findings=findings)

    @staticmethod
    def _resolve_repo_path(context: Any) -> Path | None:
        if context and hasattr(context, "target"):
            return Path(context.target)
        return None

    @staticmethod
    def _collect_license_expressions(repo_path: Path) -> list[tuple[str, str]]:
        results: list[tuple[str, str]] = []

        pyproject = repo_path / "pyproject.toml"
        if pyproject.is_file():
            try:
                data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
                lic = data.get("project", {}).get("license")
                if isinstance(lic, str):
                    results.append(("pyproject.toml", lic))
                elif isinstance(lic, dict) and "text" in lic:
                    results.append(("pyproject.toml", lic["text"]))
            except Exception as e:  # nosec B110
                logger.debug("Failed to parse pyproject.toml license: %s", e)

        pkg_json = repo_path / "package.json"
        if pkg_json.is_file():
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8"))
                lic = data.get("license")
                if isinstance(lic, str):
                    results.append(("package.json", lic))
            except Exception as e:  # nosec B110
                logger.debug("Failed to parse package.json license: %s", e)

        pom = repo_path / "pom.xml"
        if pom.is_file():
            try:
                import xml.etree.ElementTree as ET  # nosec B405

                tree = ET.parse(pom)  # nosec B314
                root = tree.getroot()
                ns = ""
                if root.tag.startswith("{"):
                    ns = root.tag.split("}")[0] + "}"
                for lic_elem in root.findall(f".//{ns}license"):
                    name_elem = lic_elem.find(f"{ns}name")
                    if name_elem is not None and name_elem.text:
                        results.append(("pom.xml", name_elem.text.strip()))
            except Exception as e:  # nosec B110
                logger.debug("Failed to parse pom.xml license: %s", e)

        return results


def _register() -> None:
    if "HYG-LIC-004" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-LIC-004", SpdxValidationRule())


_register()

__all__ = ["SpdxValidationRule"]
