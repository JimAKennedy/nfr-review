# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for license hygiene rules — copyleft, NOTICE, headers."""

from __future__ import annotations

from nfr_review.collectors.payloads.license_scan import (
    CopyleftFlags,
    LicenseDetection,
    LicenseScanPayload,
    LicenseScanSummaryPayload,
)
from nfr_review.hygiene.rules.lic_copyleft import CopyleftDetectionRule
from nfr_review.hygiene.rules.lic_headers import LicenseHeaderRule
from nfr_review.hygiene.rules.lic_notice import NoticeCompletenessRule
from nfr_review.models import Evidence


def _make_scan_ev(
    locator: str,
    spdx: str,
    *,
    copyrights: list[str] | None = None,
    holders: list[str] | None = None,
) -> Evidence:
    return Evidence(
        collector_name="license-scan",
        collector_version="0.1.0",
        locator=locator,
        kind="license-scan",
        payload=LicenseScanPayload(
            licenses=[LicenseDetection(spdx_key=spdx, score=95.0, start_line=1, end_line=10)],
            copyrights=copyrights or [],
            holders=holders or [],
            detected_expression_spdx=spdx,
        ),
    )


def _make_summary_ev(licenses: list[str], *, has_gpl: bool = False) -> Evidence:
    return Evidence(
        collector_name="license-scan",
        collector_version="0.1.0",
        locator=".",
        kind="license-scan-summary",
        payload=LicenseScanSummaryPayload(
            total_files_scanned=5,
            unique_licenses=licenses,
            copyleft_flags=CopyleftFlags(has_gpl=has_gpl, has_agpl=False, has_lgpl=False),
        ),
    )


class TestCopyleftDetection:
    def test_gpl_in_source_flagged_red_for_permissive_project(self) -> None:
        evidence = [
            _make_scan_ev("LICENSE", "Apache-2.0"),
            _make_scan_ev("src/main.py", "GPL-3.0-only"),
            _make_summary_ev(["Apache-2.0", "GPL-3.0-only"], has_gpl=True),
        ]
        rule = CopyleftDetectionRule()
        result = rule.evaluate(evidence, context=None)
        gpl_findings = [f for f in result.findings if "GPL" in f.summary]
        assert any(f.rag == "red" for f in gpl_findings)

    def test_gpl_in_source_green_for_gpl_project(self) -> None:
        evidence = [
            _make_scan_ev("LICENSE", "GPL-3.0-only"),
            _make_scan_ev("src/main.py", "GPL-3.0-only"),
            _make_summary_ev(["GPL-3.0-only"], has_gpl=True),
        ]
        rule = CopyleftDetectionRule()
        result = rule.evaluate(evidence, context=None)
        src_findings = [f for f in result.findings if "src/main.py" in f.evidence_locator]
        assert all(f.rag == "green" for f in src_findings)

    def test_no_copyleft_produces_green(self) -> None:
        evidence = [
            _make_scan_ev("LICENSE", "MIT"),
            _make_summary_ev(["MIT"]),
        ]
        rule = CopyleftDetectionRule()
        result = rule.evaluate(evidence, context=None)
        assert all(f.rag == "green" for f in result.findings)

    def test_lgpl_flagged_amber_for_permissive_project(self) -> None:
        evidence = [
            _make_scan_ev("LICENSE", "MIT"),
            _make_scan_ev("lib/widget.py", "LGPL-2.1-only"),
            _make_summary_ev(["MIT", "LGPL-2.1-only"]),
        ]
        rule = CopyleftDetectionRule()
        result = rule.evaluate(evidence, context=None)
        lgpl_findings = [f for f in result.findings if "LGPL" in f.summary]
        assert any(f.rag == "amber" for f in lgpl_findings)


class TestNoticeCompleteness:
    def test_notice_required_for_apache_project(self) -> None:
        evidence = [
            _make_scan_ev("LICENSE", "Apache-2.0"),
            _make_scan_ev("src/main.py", "Apache-2.0", holders=["Acme Corp"]),
            _make_summary_ev(["Apache-2.0"]),
        ]
        rule = NoticeCompletenessRule()
        result = rule.evaluate(evidence, context=None)
        assert any(f.rag == "red" for f in result.findings)
        assert any("NOTICE" in f.summary for f in result.findings)

    def test_notice_skipped_for_gpl_project(self) -> None:
        evidence = [
            _make_scan_ev("LICENSE", "GPL-3.0-only"),
            _make_scan_ev("src/main.py", "GPL-3.0-only", holders=["Acme Corp"]),
            _make_summary_ev(["GPL-3.0-only"], has_gpl=True),
        ]
        rule = NoticeCompletenessRule()
        result = rule.evaluate(evidence, context=None)
        assert all(f.rag == "green" for f in result.findings)
        assert any("not required" in f.summary for f in result.findings)

    def test_notice_skipped_for_lgpl_project(self) -> None:
        evidence = [
            _make_scan_ev("LICENSE", "LGPL-2.1-only"),
            _make_scan_ev("src/main.py", "LGPL-2.1-only", holders=["Acme Corp"]),
            _make_summary_ev(["LGPL-2.1-only"]),
        ]
        rule = NoticeCompletenessRule()
        result = rule.evaluate(evidence, context=None)
        assert all(f.rag == "green" for f in result.findings)


class TestLicenseHeaders:
    def test_config_files_excluded(self) -> None:
        evidence = [
            _make_scan_ev("astro.config.ts", ""),
            _make_scan_ev("src/main.ts", "Apache-2.0", copyrights=["Copyright 2026"]),
        ]
        evidence[0].payload = LicenseScanPayload(
            licenses=[], copyrights=[], holders=[], detected_expression_spdx=None
        )
        rule = LicenseHeaderRule()
        result = rule.evaluate(evidence, context=None)
        assert all(f.rag == "green" for f in result.findings)

    def test_build_dir_excluded(self) -> None:
        evidence = [
            _make_scan_ev("build/output.js", ""),
            _make_scan_ev("src/main.js", "MIT", copyrights=["Copyright 2026"]),
        ]
        evidence[0].payload = LicenseScanPayload(
            licenses=[], copyrights=[], holders=[], detected_expression_spdx=None
        )
        rule = LicenseHeaderRule()
        result = rule.evaluate(evidence, context=None)
        assert all(f.rag == "green" for f in result.findings)

    def test_missing_header_still_flagged(self) -> None:
        evidence = [
            _make_scan_ev("src/util.py", ""),
        ]
        evidence[0].payload = LicenseScanPayload(
            licenses=[], copyrights=[], holders=[], detected_expression_spdx=None
        )
        rule = LicenseHeaderRule()
        result = rule.evaluate(evidence, context=None)
        assert any(f.rag == "amber" for f in result.findings)
