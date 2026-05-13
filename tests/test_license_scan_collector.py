"""Tests for the LicenseScanCollector — unit tests with mocked scancode API
and graceful-skip behavior when scancode is not installed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from nfr_review.hygiene import hygiene_collector_registry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURE_DIRTY = Path(__file__).parent / "fixtures" / "license-dirty-repo"
FIXTURE_CLEAN = Path(__file__).parent / "fixtures" / "license-clean-repo"


def _mock_get_licenses(
    location: str,
    min_score: int = 0,
    **kwargs: Any,
) -> dict[str, Any]:
    """Return canned scancode license data based on file content."""
    if "gpl_module" in location:
        return {
            "detected_license_expression_spdx": "GPL-3.0-only",
            "license_detections": [
                {
                    "matches": [
                        {
                            "license_expression_spdx": "GPL-3.0-only",
                            "score": 95.0,
                            "start_line": 1,
                            "end_line": 15,
                        }
                    ]
                }
            ],
            "license_clues": [],
            "percentage_of_license_text": 60,
        }
    if "clean_module" in location:
        return {
            "detected_license_expression_spdx": "Apache-2.0",
            "license_detections": [
                {
                    "matches": [
                        {
                            "license_expression_spdx": "Apache-2.0",
                            "score": 98.0,
                            "start_line": 1,
                            "end_line": 13,
                        }
                    ]
                }
            ],
            "license_clues": [],
            "percentage_of_license_text": 55,
        }
    if location.upper().endswith("LICENSE") or "COPYING" in location.upper():
        if "dirty" in location:
            return {
                "detected_license_expression_spdx": "GPL-3.0-only",
                "license_detections": [
                    {
                        "matches": [
                            {
                                "license_expression_spdx": "GPL-3.0-only",
                                "score": 100.0,
                                "start_line": 1,
                                "end_line": 8,
                            }
                        ]
                    }
                ],
                "license_clues": [],
                "percentage_of_license_text": 95,
            }
        return {
            "detected_license_expression_spdx": "Apache-2.0",
            "license_detections": [
                {
                    "matches": [
                        {
                            "license_expression_spdx": "Apache-2.0",
                            "score": 100.0,
                            "start_line": 1,
                            "end_line": 20,
                        }
                    ]
                }
            ],
            "license_clues": [],
            "percentage_of_license_text": 90,
        }
    return {
        "detected_license_expression_spdx": None,
        "license_detections": [],
        "license_clues": [],
        "percentage_of_license_text": 0,
    }


def _mock_get_copyrights(
    location: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Return canned copyright data."""
    if "gpl_module" in location:
        return {
            "copyrights": [{"copyright": "Copyright (C) 2026 Example Corp."}],
            "holders": [{"holder": "Example Corp."}],
            "authors": [],
        }
    if "clean_module" in location:
        return {
            "copyrights": [{"copyright": "Copyright 2026 Example Corp."}],
            "holders": [{"holder": "Example Corp."}],
            "authors": [],
        }
    return {"copyrights": [], "holders": [], "authors": []}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_collector_registered(self) -> None:
        import nfr_review.hygiene.collectors  # noqa: F401  # trigger registration

        assert "license-scan" in hygiene_collector_registry

    def test_collector_protocol(self) -> None:
        import nfr_review.hygiene.collectors  # noqa: F401

        collector = hygiene_collector_registry.get("license-scan")
        assert hasattr(collector, "name")
        assert hasattr(collector, "version")
        assert hasattr(collector, "collect")
        assert collector.name == "license-scan"


# ---------------------------------------------------------------------------
# Graceful skip when scancode not installed
# ---------------------------------------------------------------------------


class TestGracefulSkip:
    def test_returns_empty_when_scancode_unavailable(self, tmp_path: Path) -> None:
        from nfr_review.hygiene.collectors import license_scan

        original = license_scan._SCANCODE_AVAILABLE
        try:
            license_scan._SCANCODE_AVAILABLE = False
            collector = license_scan.LicenseScanCollector()
            result = collector.collect(tmp_path, None)
            assert result == []
        finally:
            license_scan._SCANCODE_AVAILABLE = original

    def test_logs_warning_when_unavailable(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        from nfr_review.hygiene.collectors import license_scan

        original = license_scan._SCANCODE_AVAILABLE
        try:
            license_scan._SCANCODE_AVAILABLE = False
            collector = license_scan.LicenseScanCollector()
            log_name = "nfr_review.hygiene.collectors.license_scan"
            with caplog.at_level("WARNING", logger=log_name):
                collector.collect(tmp_path, None)
            assert any("scancode-toolkit not installed" in r.message for r in caplog.records)
        finally:
            license_scan._SCANCODE_AVAILABLE = original


# ---------------------------------------------------------------------------
# Unit tests with mocked scancode API
# ---------------------------------------------------------------------------


@patch(
    "nfr_review.hygiene.collectors.license_scan.get_copyrights",
    side_effect=_mock_get_copyrights,
)
@patch(
    "nfr_review.hygiene.collectors.license_scan.get_licenses",
    side_effect=_mock_get_licenses,
)
class TestDirtyRepo:
    def test_produces_evidence(self, mock_lic: MagicMock, mock_cr: MagicMock) -> None:
        from nfr_review.hygiene.collectors.license_scan import LicenseScanCollector

        collector = LicenseScanCollector()
        with patch("nfr_review.hygiene.collectors.license_scan._SCANCODE_AVAILABLE", True):
            evidence = collector.collect(FIXTURE_DIRTY, None)

        assert len(evidence) >= 2
        per_file = [e for e in evidence if e.kind == "license-scan"]
        summaries = [e for e in evidence if e.kind == "license-scan-summary"]
        assert len(per_file) >= 1
        assert len(summaries) == 1

    def test_detects_gpl(self, mock_lic: MagicMock, mock_cr: MagicMock) -> None:
        from nfr_review.hygiene.collectors.license_scan import LicenseScanCollector

        collector = LicenseScanCollector()
        with patch("nfr_review.hygiene.collectors.license_scan._SCANCODE_AVAILABLE", True):
            evidence = collector.collect(FIXTURE_DIRTY, None)

        summary = next(e for e in evidence if e.kind == "license-scan-summary")
        assert summary.payload["copyleft_flags"]["has_gpl"] is True

    def test_summary_has_gpl_in_unique_licenses(
        self, mock_lic: MagicMock, mock_cr: MagicMock
    ) -> None:
        from nfr_review.hygiene.collectors.license_scan import LicenseScanCollector

        collector = LicenseScanCollector()
        with patch("nfr_review.hygiene.collectors.license_scan._SCANCODE_AVAILABLE", True):
            evidence = collector.collect(FIXTURE_DIRTY, None)

        summary = next(e for e in evidence if e.kind == "license-scan-summary")
        assert "GPL-3.0-only" in summary.payload["unique_licenses"]

    def test_copyrights_extracted(self, mock_lic: MagicMock, mock_cr: MagicMock) -> None:
        from nfr_review.hygiene.collectors.license_scan import LicenseScanCollector

        collector = LicenseScanCollector()
        with patch("nfr_review.hygiene.collectors.license_scan._SCANCODE_AVAILABLE", True):
            evidence = collector.collect(FIXTURE_DIRTY, None)

        gpl_file = [
            e for e in evidence if e.kind == "license-scan" and "gpl_module" in e.locator
        ]
        assert len(gpl_file) == 1
        assert "Copyright (C) 2026 Example Corp." in gpl_file[0].payload["copyrights"]


@patch(
    "nfr_review.hygiene.collectors.license_scan.get_copyrights",
    side_effect=_mock_get_copyrights,
)
@patch(
    "nfr_review.hygiene.collectors.license_scan.get_licenses",
    side_effect=_mock_get_licenses,
)
class TestCleanRepo:
    def test_no_copyleft(self, mock_lic: MagicMock, mock_cr: MagicMock) -> None:
        from nfr_review.hygiene.collectors.license_scan import LicenseScanCollector

        collector = LicenseScanCollector()
        with patch("nfr_review.hygiene.collectors.license_scan._SCANCODE_AVAILABLE", True):
            evidence = collector.collect(FIXTURE_CLEAN, None)

        summary = next(e for e in evidence if e.kind == "license-scan-summary")
        flags = summary.payload["copyleft_flags"]
        assert flags["has_gpl"] is False
        assert flags["has_agpl"] is False
        assert flags["has_lgpl"] is False

    def test_apache_detected(self, mock_lic: MagicMock, mock_cr: MagicMock) -> None:
        from nfr_review.hygiene.collectors.license_scan import LicenseScanCollector

        collector = LicenseScanCollector()
        with patch("nfr_review.hygiene.collectors.license_scan._SCANCODE_AVAILABLE", True):
            evidence = collector.collect(FIXTURE_CLEAN, None)

        summary = next(e for e in evidence if e.kind == "license-scan-summary")
        assert "Apache-2.0" in summary.payload["unique_licenses"]


# ---------------------------------------------------------------------------
# Empty repo
# ---------------------------------------------------------------------------


class TestEmptyRepo:
    def test_empty_dir_produces_summary_only(self, tmp_path: Path) -> None:
        from nfr_review.hygiene.collectors.license_scan import LicenseScanCollector

        with (
            patch("nfr_review.hygiene.collectors.license_scan._SCANCODE_AVAILABLE", True),
            patch(
                "nfr_review.hygiene.collectors.license_scan.get_licenses",
                return_value={
                    "detected_license_expression_spdx": None,
                    "license_detections": [],
                    "license_clues": [],
                    "percentage_of_license_text": 0,
                },
            ),
            patch(
                "nfr_review.hygiene.collectors.license_scan.get_copyrights",
                return_value={"copyrights": [], "holders": [], "authors": []},
            ),
        ):
            collector = LicenseScanCollector()
            evidence = collector.collect(tmp_path, None)

        summaries = [e for e in evidence if e.kind == "license-scan-summary"]
        assert len(summaries) == 1
        assert summaries[0].payload["total_files_scanned"] == 0
        assert summaries[0].payload["unique_licenses"] == []


# ---------------------------------------------------------------------------
# Min-score filtering
# ---------------------------------------------------------------------------


class TestMinScoreFiltering:
    def test_low_score_matches_excluded(self, tmp_path: Path) -> None:
        from nfr_review.hygiene.collectors.license_scan import LicenseScanCollector

        src = tmp_path / "app.py"
        src.write_text("# some code\n", encoding="utf-8")

        low_score_response = {
            "detected_license_expression_spdx": "MIT",
            "license_detections": [
                {
                    "matches": [
                        {
                            "license_expression_spdx": "MIT",
                            "score": 20.0,
                            "start_line": 1,
                            "end_line": 1,
                        }
                    ]
                }
            ],
            "license_clues": [],
            "percentage_of_license_text": 5,
        }

        with (
            patch("nfr_review.hygiene.collectors.license_scan._SCANCODE_AVAILABLE", True),
            patch(
                "nfr_review.hygiene.collectors.license_scan.get_licenses",
                return_value=low_score_response,
            ),
            patch(
                "nfr_review.hygiene.collectors.license_scan.get_copyrights",
                return_value={"copyrights": [], "holders": [], "authors": []},
            ),
        ):
            collector = LicenseScanCollector()
            evidence = collector.collect(tmp_path, None)

        per_file = [e for e in evidence if e.kind == "license-scan"]
        assert len(per_file) == 1
        assert per_file[0].payload["licenses"] == []

        summary = next(e for e in evidence if e.kind == "license-scan-summary")
        assert summary.payload["unique_licenses"] == []


# ---------------------------------------------------------------------------
# Scan error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_scan_error_does_not_crash(self, tmp_path: Path) -> None:
        from nfr_review.hygiene.collectors.license_scan import LicenseScanCollector

        src = tmp_path / "broken.py"
        src.write_text("# broken\n", encoding="utf-8")

        with (
            patch("nfr_review.hygiene.collectors.license_scan._SCANCODE_AVAILABLE", True),
            patch(
                "nfr_review.hygiene.collectors.license_scan.get_licenses",
                side_effect=RuntimeError("scan failed"),
            ),
            patch(
                "nfr_review.hygiene.collectors.license_scan.get_copyrights",
                side_effect=RuntimeError("scan failed"),
            ),
        ):
            collector = LicenseScanCollector()
            evidence = collector.collect(tmp_path, None)

        assert len(evidence) >= 1
        summary = next(e for e in evidence if e.kind == "license-scan-summary")
        assert summary.payload["total_files_scanned"] == 1


# ---------------------------------------------------------------------------
# LGPL and AGPL flag detection
# ---------------------------------------------------------------------------


class TestCopyleftVariants:
    def test_lgpl_flag(self, tmp_path: Path) -> None:
        from nfr_review.hygiene.collectors.license_scan import LicenseScanCollector

        src = tmp_path / "lib.py"
        src.write_text("# lgpl code\n", encoding="utf-8")

        lgpl_response = {
            "detected_license_expression_spdx": "LGPL-2.1-only",
            "license_detections": [
                {
                    "matches": [
                        {
                            "license_expression_spdx": "LGPL-2.1-only",
                            "score": 90.0,
                            "start_line": 1,
                            "end_line": 5,
                        }
                    ]
                }
            ],
            "license_clues": [],
            "percentage_of_license_text": 40,
        }

        with (
            patch("nfr_review.hygiene.collectors.license_scan._SCANCODE_AVAILABLE", True),
            patch(
                "nfr_review.hygiene.collectors.license_scan.get_licenses",
                return_value=lgpl_response,
            ),
            patch(
                "nfr_review.hygiene.collectors.license_scan.get_copyrights",
                return_value={"copyrights": [], "holders": [], "authors": []},
            ),
        ):
            collector = LicenseScanCollector()
            evidence = collector.collect(tmp_path, None)

        summary = next(e for e in evidence if e.kind == "license-scan-summary")
        assert summary.payload["copyleft_flags"]["has_lgpl"] is True
        assert summary.payload["copyleft_flags"]["has_gpl"] is False

    def test_agpl_flag(self, tmp_path: Path) -> None:
        from nfr_review.hygiene.collectors.license_scan import LicenseScanCollector

        src = tmp_path / "server.py"
        src.write_text("# agpl code\n", encoding="utf-8")

        agpl_response = {
            "detected_license_expression_spdx": "AGPL-3.0-only",
            "license_detections": [
                {
                    "matches": [
                        {
                            "license_expression_spdx": "AGPL-3.0-only",
                            "score": 92.0,
                            "start_line": 1,
                            "end_line": 10,
                        }
                    ]
                }
            ],
            "license_clues": [],
            "percentage_of_license_text": 50,
        }

        with (
            patch("nfr_review.hygiene.collectors.license_scan._SCANCODE_AVAILABLE", True),
            patch(
                "nfr_review.hygiene.collectors.license_scan.get_licenses",
                return_value=agpl_response,
            ),
            patch(
                "nfr_review.hygiene.collectors.license_scan.get_copyrights",
                return_value={"copyrights": [], "holders": [], "authors": []},
            ),
        ):
            collector = LicenseScanCollector()
            evidence = collector.collect(tmp_path, None)

        summary = next(e for e in evidence if e.kind == "license-scan-summary")
        assert summary.payload["copyleft_flags"]["has_agpl"] is True
        assert summary.payload["copyleft_flags"]["has_gpl"] is False


# ---------------------------------------------------------------------------
# Integration tests (only run when scancode is installed)
# ---------------------------------------------------------------------------


_has_scancode = True
try:
    import scancode  # noqa: F401
except ImportError:
    _has_scancode = False

_skip_no_scancode = pytest.mark.skipif(
    not _has_scancode, reason="scancode-toolkit not installed"
)


@_skip_no_scancode
class TestIntegrationDirtyRepo:
    def test_real_scan_detects_gpl(self) -> None:
        from nfr_review.hygiene.collectors.license_scan import LicenseScanCollector

        collector = LicenseScanCollector()
        evidence = collector.collect(FIXTURE_DIRTY, None)

        summary = next(e for e in evidence if e.kind == "license-scan-summary")
        assert summary.payload["copyleft_flags"]["has_gpl"] is True

    def test_real_scan_finds_license_files(self) -> None:
        from nfr_review.hygiene.collectors.license_scan import LicenseScanCollector

        collector = LicenseScanCollector()
        evidence = collector.collect(FIXTURE_DIRTY, None)

        locators = {e.locator for e in evidence if e.kind == "license-scan"}
        assert any("LICENSE" in loc for loc in locators)


@_skip_no_scancode
class TestIntegrationCleanRepo:
    def test_real_scan_no_copyleft(self) -> None:
        from nfr_review.hygiene.collectors.license_scan import LicenseScanCollector

        collector = LicenseScanCollector()
        evidence = collector.collect(FIXTURE_CLEAN, None)

        summary = next(e for e in evidence if e.kind == "license-scan-summary")
        flags = summary.payload["copyleft_flags"]
        assert flags["has_gpl"] is False
        assert flags["has_agpl"] is False

    def test_real_scan_finds_apache(self) -> None:
        from nfr_review.hygiene.collectors.license_scan import LicenseScanCollector

        collector = LicenseScanCollector()
        evidence = collector.collect(FIXTURE_CLEAN, None)

        summary = next(e for e in evidence if e.kind == "license-scan-summary")
        assert any("apache" in lic.lower() for lic in summary.payload["unique_licenses"])
