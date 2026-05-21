# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""License scan collector — uses scancode-toolkit to detect licenses and
copyrights in source files.  Gracefully skips when scancode is not installed.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from nfr_review.hygiene import hygiene_collector_registry
from nfr_review.models import Evidence
from nfr_review.path_filter import iter_repo_files

logger = logging.getLogger(__name__)

_SCANCODE_AVAILABLE = False

try:
    from scancode.api import get_copyrights as get_copyrights  # type: ignore[import-untyped]  # noqa: I001
    from scancode.api import get_licenses as get_licenses  # type: ignore[import-untyped]

    _SCANCODE_AVAILABLE = True
except ImportError:

    def get_licenses(location: str, **kwargs: Any) -> dict[str, Any]:  # type: ignore[misc]
        raise RuntimeError("scancode not installed")

    def get_copyrights(location: str, **kwargs: Any) -> dict[str, Any]:  # type: ignore[misc]
        raise RuntimeError("scancode not installed")


_SOURCE_EXTENSIONS = frozenset(
    {
        ".py",
        ".java",
        ".go",
        ".js",
        ".ts",
        ".jsx",
        ".tsx",
        ".cs",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".rs",
        ".rb",
        ".swift",
        ".kt",
        ".scala",
        ".sh",
        ".bash",
    }
)


def _iter_source_files(repo_path: Path) -> list[Path]:
    """Return source files in the repo, respecting .gitignore when available."""
    return [p for p in iter_repo_files(repo_path) if p.suffix in _SOURCE_EXTENSIONS]


class LicenseScanCollector:
    name = "license-scan"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        if not _SCANCODE_AVAILABLE:
            logger.warning(
                "scancode-toolkit not installed — skipping license scan. "
                "Install with: pip install nfr-review[scancode]"
            )
            return []

        min_score = 50
        if config and hasattr(config, "extra"):
            sc_cfg = getattr(config.extra, "scancode", None)
            if sc_cfg and isinstance(sc_cfg, dict):
                min_score = sc_cfg.get("min_score", 50)

        source_files = _iter_source_files(repo_path)
        all_files = source_files + _collect_license_files(repo_path)

        evidence: list[Evidence] = []
        all_licenses: list[str] = []
        copyleft_flags: dict[str, bool] = {
            "has_gpl": False,
            "has_agpl": False,
            "has_lgpl": False,
        }

        for fpath in all_files:
            rel = str(fpath.relative_to(repo_path))
            logger.debug("Scanning %s", rel)

            try:
                lic_data = get_licenses(str(fpath), min_score=min_score)
            except Exception:
                logger.warning("License scan failed for %s", rel, exc_info=True)
                lic_data = {}

            try:
                cr_data = get_copyrights(str(fpath))
            except Exception:
                logger.warning("Copyright scan failed for %s", rel, exc_info=True)
                cr_data = {}

            expr = lic_data.get("detected_license_expression_spdx")
            detections = lic_data.get("license_detections", [])
            copyrights = cr_data.get("copyrights", [])
            holders = cr_data.get("holders", [])

            licenses_found: list[dict[str, Any]] = []
            for det in detections:
                for match in det.get("matches", []):
                    spdx = match.get("license_expression_spdx", "")
                    score = match.get("score", 0)
                    if score >= min_score:
                        entry: dict[str, Any] = {
                            "spdx_key": spdx,
                            "score": score,
                            "start_line": match.get("start_line", 0),
                            "end_line": match.get("end_line", 0),
                        }
                        licenses_found.append(entry)
                        all_licenses.append(spdx)
                        spdx_lower = spdx.lower()
                        if "agpl" in spdx_lower:
                            copyleft_flags["has_agpl"] = True
                        elif "lgpl" in spdx_lower:
                            copyleft_flags["has_lgpl"] = True
                        elif "gpl" in spdx_lower:
                            copyleft_flags["has_gpl"] = True

            payload: dict[str, Any] = {
                "licenses": licenses_found,
                "copyrights": [c.get("copyright", "") for c in copyrights],
                "holders": [h.get("holder", "") for h in holders],
                "detected_expression_spdx": expr,
            }

            evidence.append(
                Evidence(
                    collector_name=self.name,
                    collector_version=self.version,
                    locator=rel,
                    kind="license-scan",
                    payload=payload,
                )
            )

        unique_licenses = sorted(set(all_licenses))
        summary_payload: dict[str, Any] = {
            "total_files_scanned": len(all_files),
            "unique_licenses": unique_licenses,
            "copyleft_flags": copyleft_flags,
        }

        evidence.append(
            Evidence(
                collector_name=self.name,
                collector_version=self.version,
                locator=".",
                kind="license-scan-summary",
                payload=summary_payload,
            )
        )

        return evidence


def _collect_license_files(repo_path: Path) -> list[Path]:
    """Collect LICENSE, NOTICE, and similar top-level files."""
    names = {"LICENSE", "LICENCE", "NOTICE", "COPYING"}
    found: list[Path] = []
    for item in repo_path.iterdir():
        if item.is_file() and item.stem.upper() in names:
            found.append(item)
    return sorted(found)


def _register() -> None:
    if "license-scan" not in hygiene_collector_registry:
        hygiene_collector_registry.register("license-scan", LicenseScanCollector())


_register()

__all__ = ["LicenseScanCollector"]
