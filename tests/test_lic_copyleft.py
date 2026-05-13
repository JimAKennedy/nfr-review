"""Tests for HYG-LIC-001: Copyleft license detection rule."""

from __future__ import annotations

from typing import Any

from nfr_review.hygiene.rules.lic_copyleft import CopyleftDetectionRule
from nfr_review.models import Evidence

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_evidence(
    locator: str = "src/app.py",
    licenses: list[dict[str, Any]] | None = None,
    kind: str = "license-scan",
) -> Evidence:
    return Evidence(
        collector_name="license-scan",
        collector_version="0.1.0",
        locator=locator,
        kind=kind,
        payload={
            "licenses": licenses or [],
            "copyrights": [],
            "holders": [],
            "detected_expression_spdx": None,
        },
    )


def _make_summary(
    unique_licenses: list[str] | None = None,
    copyleft_flags: dict[str, bool] | None = None,
) -> Evidence:
    return Evidence(
        collector_name="license-scan",
        collector_version="0.1.0",
        locator=".",
        kind="license-scan-summary",
        payload={
            "total_files_scanned": 1,
            "unique_licenses": unique_licenses or [],
            "copyleft_flags": copyleft_flags
            or {"has_gpl": False, "has_agpl": False, "has_lgpl": False},
        },
    )


def _lic(spdx: str, score: float = 95.0) -> dict[str, Any]:
    return {"spdx_key": spdx, "score": score, "start_line": 1, "end_line": 10}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_rule_registered(self) -> None:
        import nfr_review.hygiene.rules  # noqa: F401
        from nfr_review.hygiene import hygiene_rule_registry

        assert "HYG-LIC-001" in hygiene_rule_registry

    def test_rule_attributes(self) -> None:
        rule = CopyleftDetectionRule()
        assert rule.id == "HYG-LIC-001"
        assert rule.band == 1
        assert rule.required_collectors == ["license-scan"]
        assert rule.category == "license"


# ---------------------------------------------------------------------------
# No evidence → skipped
# ---------------------------------------------------------------------------


class TestNoEvidence:
    def test_skipped_when_no_evidence(self) -> None:
        rule = CopyleftDetectionRule()
        result = rule.evaluate([], None)
        assert result.skipped is True
        assert "no license-scan evidence" in (result.skip_reason or "")


# ---------------------------------------------------------------------------
# GPL source file → red
# ---------------------------------------------------------------------------


class TestGPLSourceFile:
    def test_gpl_produces_red(self) -> None:
        ev = _make_evidence(
            locator="src/gpl_module.py",
            licenses=[_lic("GPL-3.0-only")],
        )
        summary = _make_summary(
            unique_licenses=["GPL-3.0-only"],
            copyleft_flags={"has_gpl": True, "has_agpl": False, "has_lgpl": False},
        )
        rule = CopyleftDetectionRule()
        result = rule.evaluate([ev, summary], None)

        assert result.skipped is False
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "red"
        assert f.severity == "high"
        assert "GPL-3.0-only" in f.summary
        assert "copyleft-detection" == f.pattern_tag

    def test_gpl2_produces_red(self) -> None:
        ev = _make_evidence(licenses=[_lic("GPL-2.0-or-later")])
        rule = CopyleftDetectionRule()
        result = rule.evaluate([ev, _make_summary()], None)

        assert result.findings[0].rag == "red"


# ---------------------------------------------------------------------------
# AGPL → red
# ---------------------------------------------------------------------------


class TestAGPL:
    def test_agpl_produces_red(self) -> None:
        ev = _make_evidence(licenses=[_lic("AGPL-3.0-only")])
        rule = CopyleftDetectionRule()
        result = rule.evaluate([ev, _make_summary()], None)

        assert len(result.findings) == 1
        assert result.findings[0].rag == "red"
        assert result.findings[0].severity == "high"
        assert "AGPL-3.0-only" in result.findings[0].summary


# ---------------------------------------------------------------------------
# LGPL → amber
# ---------------------------------------------------------------------------


class TestLGPL:
    def test_lgpl_produces_amber(self) -> None:
        ev = _make_evidence(licenses=[_lic("LGPL-2.1-only")])
        rule = CopyleftDetectionRule()
        result = rule.evaluate([ev, _make_summary()], None)

        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "amber"
        assert f.severity == "medium"
        assert "dynamic linking" in f.summary.lower()


# ---------------------------------------------------------------------------
# MPL → amber (weak copyleft)
# ---------------------------------------------------------------------------


class TestMPL:
    def test_mpl_produces_amber(self) -> None:
        ev = _make_evidence(licenses=[_lic("MPL-2.0")])
        rule = CopyleftDetectionRule()
        result = rule.evaluate([ev, _make_summary()], None)

        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"


# ---------------------------------------------------------------------------
# All permissive → green
# ---------------------------------------------------------------------------


class TestAllPermissive:
    def test_apache_only_produces_green(self) -> None:
        ev = _make_evidence(licenses=[_lic("Apache-2.0")])
        rule = CopyleftDetectionRule()
        result = rule.evaluate([ev, _make_summary()], None)

        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert result.findings[0].severity == "info"

    def test_mit_only_produces_green(self) -> None:
        ev = _make_evidence(licenses=[_lic("MIT")])
        rule = CopyleftDetectionRule()
        result = rule.evaluate([ev, _make_summary()], None)

        assert result.findings[0].rag == "green"

    def test_no_licenses_produces_green(self) -> None:
        ev = _make_evidence(licenses=[])
        rule = CopyleftDetectionRule()
        result = rule.evaluate([ev, _make_summary()], None)

        assert result.findings[0].rag == "green"


# ---------------------------------------------------------------------------
# Multiple licenses in one file
# ---------------------------------------------------------------------------


class TestMultipleLicenses:
    def test_mixed_gpl_and_mit(self) -> None:
        ev = _make_evidence(
            licenses=[_lic("MIT"), _lic("GPL-3.0-only")],
        )
        rule = CopyleftDetectionRule()
        result = rule.evaluate([ev, _make_summary()], None)

        rags = {f.rag for f in result.findings}
        assert "red" in rags

    def test_multiple_files_mixed(self) -> None:
        ev1 = _make_evidence(locator="a.py", licenses=[_lic("MIT")])
        ev2 = _make_evidence(locator="b.py", licenses=[_lic("LGPL-2.1-only")])
        rule = CopyleftDetectionRule()
        result = rule.evaluate([ev1, ev2, _make_summary()], None)

        rags = {f.rag for f in result.findings}
        assert "amber" in rags
        assert len(result.findings) == 1


# ---------------------------------------------------------------------------
# Summary-only evidence (no per-file)
# ---------------------------------------------------------------------------


class TestSummaryOnly:
    def test_summary_only_produces_green(self) -> None:
        summary = _make_summary(unique_licenses=["Apache-2.0"])
        rule = CopyleftDetectionRule()
        result = rule.evaluate([summary], None)

        assert result.skipped is False
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
