"""Tests for HYG-LIC-002: NOTICE file completeness rule."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from nfr_review.hygiene.rules.lic_notice import NoticeCompletenessRule
from nfr_review.models import Evidence


def _make_file_ev(
    locator: str = "src/app.py",
    holders: list[str] | None = None,
) -> Evidence:
    return Evidence(
        collector_name="license-scan",
        collector_version="0.1.0",
        locator=locator,
        kind="license-scan",
        payload={
            "licenses": [],
            "copyrights": [],
            "holders": holders or [],
            "detected_expression_spdx": None,
        },
    )


def _make_summary() -> Evidence:
    return Evidence(
        collector_name="license-scan",
        collector_version="0.1.0",
        locator=".",
        kind="license-scan-summary",
        payload={
            "total_files_scanned": 1,
            "unique_licenses": [],
            "copyleft_flags": {
                "has_gpl": False,
                "has_agpl": False,
                "has_lgpl": False,
            },
        },
    )


class TestRegistration:
    def test_rule_registered(self) -> None:
        import nfr_review.hygiene.rules  # noqa: F401
        from nfr_review.hygiene import hygiene_rule_registry

        assert "HYG-LIC-002" in hygiene_rule_registry


class TestNoEvidence:
    def test_skipped_when_no_evidence(self) -> None:
        rule = NoticeCompletenessRule()
        result = rule.evaluate([], None)
        assert result.skipped is True


class TestNoHolders:
    def test_green_when_no_holders(self) -> None:
        ev = _make_file_ev(holders=[])
        rule = NoticeCompletenessRule()
        result = rule.evaluate([ev, _make_summary()], None)

        assert result.findings[0].rag == "green"


class TestMissingNotice:
    def test_red_when_notice_missing_and_holders_exist(self, tmp_path: Path) -> None:
        ev = _make_file_ev(holders=["Example Corp."])
        context = SimpleNamespace(target=str(tmp_path))

        rule = NoticeCompletenessRule()
        result = rule.evaluate([ev, _make_summary()], context)

        assert result.findings[0].rag == "red"
        assert "missing" in result.findings[0].summary.lower()


class TestIncompleteNotice:
    def test_amber_when_holder_not_in_notice(self, tmp_path: Path) -> None:
        (tmp_path / "NOTICE").write_text(
            "Some Project\nCopyright Other Corp.\n",
            encoding="utf-8",
        )
        ev = _make_file_ev(holders=["Example Corp."])
        context = SimpleNamespace(target=str(tmp_path))

        rule = NoticeCompletenessRule()
        result = rule.evaluate([ev, _make_summary()], context)

        assert result.findings[0].rag == "amber"
        assert "Example Corp." in result.findings[0].summary


class TestCompleteNotice:
    def test_green_when_all_holders_covered(self, tmp_path: Path) -> None:
        (tmp_path / "NOTICE").write_text(
            "My Project\nCopyright Example Corp.\n",
            encoding="utf-8",
        )
        ev = _make_file_ev(holders=["Example Corp."])
        context = SimpleNamespace(target=str(tmp_path))

        rule = NoticeCompletenessRule()
        result = rule.evaluate([ev, _make_summary()], context)

        assert result.findings[0].rag == "green"


class TestNoContext:
    def test_red_when_context_missing(self) -> None:
        ev = _make_file_ev(holders=["Example Corp."])
        rule = NoticeCompletenessRule()
        result = rule.evaluate([ev, _make_summary()], None)

        assert result.findings[0].rag == "red"
