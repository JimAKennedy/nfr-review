"""Integration tests for PATCH-TELEM rules — run Engine.run() against
telemetry fixture repos and verify findings through the full pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

import nfr_review.collectors  # noqa: F401 — trigger collector auto-registration
import nfr_review.rules  # noqa: F401 — trigger rule auto-registration
from nfr_review.config import Config, RulesConfig
from nfr_review.engine import Engine, RunResult

GOOD_REPO = Path(__file__).parent / "fixtures" / "telemetry-good-repo"
SAMPLE_REPO = Path(__file__).parent / "fixtures" / "telemetry-sample-repo"


def _telem_config() -> Config:
    return Config(
        rules=RulesConfig(
            include_only=["PATCH-TELEM-001", "PATCH-TELEM-002", "PATCH-TELEM-003"]
        )
    )


def _run(target: Path) -> RunResult:
    engine = Engine()
    return engine.run(target=target, config=_telem_config())


def _findings_by_rule(result: RunResult, rule_id: str) -> list:
    return [f for f in result.findings if f.rule_id == rule_id]


class TestGoodRepo:
    """telemetry-good-repo has full OTel config (metrics+traces+logs),
    mandatory labels (service, version, ring, side), and Grafana synthetics."""

    @pytest.fixture(autouse=True)
    def run_engine(self) -> None:
        self.result = _run(GOOD_REPO)

    def test_telem_rules_not_skipped(self) -> None:
        telem_rrs = [
            rr for rr in self.result.rule_results if rr.rule_id.startswith("PATCH-TELEM")
        ]
        assert len(telem_rrs) == 3
        for rr in telem_rrs:
            assert not rr.skipped, f"{rr.rule_id} was skipped: {rr.skip_reason}"

    def test_golden_signal_green(self) -> None:
        findings = _findings_by_rule(self.result, "PATCH-TELEM-001")
        assert len(findings) == 1
        assert findings[0].rag == "green"

    def test_mandatory_labels_green(self) -> None:
        findings = _findings_by_rule(self.result, "PATCH-TELEM-002")
        assert len(findings) == 1
        assert findings[0].rag == "green"

    def test_synthetic_config_green(self) -> None:
        findings = _findings_by_rule(self.result, "PATCH-TELEM-003")
        assert len(findings) == 1
        assert findings[0].rag == "green"
        assert "grafana" in findings[0].summary.lower()

    def test_all_findings_have_correct_collector(self) -> None:
        for f in self.result.findings:
            assert f.collector_name == "telemetry-config"

    def test_all_findings_have_pattern_tags(self) -> None:
        for f in self.result.findings:
            assert f.pattern_tag.startswith("patch-telem-")


class TestSampleRepo:
    """telemetry-sample-repo has metrics+traces (no logs), missing ring/side
    labels, and a Datadog synthetic test — produces amber for labels."""

    @pytest.fixture(autouse=True)
    def run_engine(self) -> None:
        self.result = _run(SAMPLE_REPO)

    def test_telem_rules_not_skipped(self) -> None:
        telem_rrs = [
            rr for rr in self.result.rule_results if rr.rule_id.startswith("PATCH-TELEM")
        ]
        assert len(telem_rrs) == 3
        for rr in telem_rrs:
            assert not rr.skipped, f"{rr.rule_id} was skipped: {rr.skip_reason}"

    def test_golden_signal_green(self) -> None:
        findings = _findings_by_rule(self.result, "PATCH-TELEM-001")
        assert len(findings) == 1
        assert findings[0].rag == "green"

    def test_mandatory_labels_amber(self) -> None:
        findings = _findings_by_rule(self.result, "PATCH-TELEM-002")
        assert len(findings) == 1
        f = findings[0]
        assert f.rag == "amber"
        assert "ring" in f.summary
        assert "side" in f.summary

    def test_synthetic_config_green(self) -> None:
        findings = _findings_by_rule(self.result, "PATCH-TELEM-003")
        assert len(findings) == 1
        assert findings[0].rag == "green"
        assert "datadog" in findings[0].summary.lower()


class TestEmptyRepo:
    """An empty directory should produce info-level findings, not crashes."""

    def test_info_findings_on_empty(self, tmp_path: Path) -> None:
        result = _run(tmp_path)
        telem_rrs = [rr for rr in result.rule_results if rr.rule_id.startswith("PATCH-TELEM")]
        assert len(telem_rrs) == 3
        for rr in telem_rrs:
            assert not rr.skipped, f"{rr.rule_id} was skipped: {rr.skip_reason}"
        telem_findings = [f for f in result.findings if f.rule_id.startswith("PATCH-TELEM")]
        assert len(telem_findings) == 3
        for f in telem_findings:
            assert f.rag == "green"
            assert f.severity == "info"
