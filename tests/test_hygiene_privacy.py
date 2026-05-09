"""Tests for the privacy collector and HYG-PRV-001/002/003 rules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nfr_review.hygiene import hygiene_collector_registry, hygiene_rule_registry
from nfr_review.hygiene.collectors.privacy import PrivacyCollector
from nfr_review.hygiene.rules.prv_internal_refs import InternalRefsRule
from nfr_review.hygiene.rules.prv_pii_patterns import PiiPatternsRule
from nfr_review.hygiene.rules.prv_tracking_ids import TrackingIdsRule
from nfr_review.models import Evidence

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_evidence(
    pii: list[dict[str, Any]] | None = None,
    internal: list[dict[str, Any]] | None = None,
    tracking: list[dict[str, Any]] | None = None,
    files_scanned: int = 1,
) -> list[Evidence]:
    return [
        Evidence(
            collector_name="privacy",
            collector_version="0.1.0",
            locator=".",
            kind="privacy-analysis",
            payload={
                "pii_matches": pii or [],
                "internal_references": internal or [],
                "tracking_ids": tracking or [],
                "files_scanned": files_scanned,
            },
        )
    ]


def _match(
    file: str = "app.py",
    line: int = 1,
    pattern_type: str = "email",
    snippet: str = "test snippet",
) -> dict[str, Any]:
    return {"file": file, "line": line, "pattern_type": pattern_type, "snippet": snippet}


def _write_file(base: Path, rel: str, content: str) -> None:
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_collector_registered(self) -> None:
        assert "privacy" in hygiene_collector_registry

    def test_collector_instance_type(self) -> None:
        assert isinstance(hygiene_collector_registry.get("privacy"), PrivacyCollector)

    def test_rule_001_registered(self) -> None:
        assert "HYG-PRV-001" in hygiene_rule_registry

    def test_rule_002_registered(self) -> None:
        assert "HYG-PRV-002" in hygiene_rule_registry

    def test_rule_003_registered(self) -> None:
        assert "HYG-PRV-003" in hygiene_rule_registry

    def test_rule_001_category(self) -> None:
        rule = hygiene_rule_registry.get("HYG-PRV-001")
        assert rule.category == "privacy"

    def test_rule_002_category(self) -> None:
        rule = hygiene_rule_registry.get("HYG-PRV-002")
        assert rule.category == "privacy"

    def test_rule_003_category(self) -> None:
        rule = hygiene_rule_registry.get("HYG-PRV-003")
        assert rule.category == "privacy"


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


class TestPrivacyCollector:
    def test_clean_source_no_matches(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "main.py", "print('hello world')\n")
        collector = PrivacyCollector()
        evs = collector.collect(tmp_path, None)
        assert len(evs) == 1
        assert evs[0].kind == "privacy-analysis"
        assert evs[0].payload["pii_matches"] == []
        assert evs[0].payload["internal_references"] == []
        assert evs[0].payload["tracking_ids"] == []
        assert evs[0].payload["files_scanned"] == 1

    def test_email_detected(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "config.py", "EMAIL = 'user@example.com'\n")
        evs = PrivacyCollector().collect(tmp_path, None)
        pii = evs[0].payload["pii_matches"]
        assert any(m["pattern_type"] == "email" for m in pii)

    def test_ssn_detected(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "data.py", "ssn = '123-45-6789'\n")
        evs = PrivacyCollector().collect(tmp_path, None)
        pii = evs[0].payload["pii_matches"]
        assert any(m["pattern_type"] == "ssn" for m in pii)

    def test_credit_card_detected(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "pay.py", "cc = '4111-1111-1111-1111'\n")
        evs = PrivacyCollector().collect(tmp_path, None)
        pii = evs[0].payload["pii_matches"]
        assert any(m["pattern_type"] == "credit_card" for m in pii)

    def test_phone_detected(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "contact.py", "phone = '(555) 123-4567'\n")
        evs = PrivacyCollector().collect(tmp_path, None)
        pii = evs[0].payload["pii_matches"]
        assert any(m["pattern_type"] == "phone" for m in pii)

    def test_pyproject_email_excluded(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "pyproject.toml",
            '[project]\nauthors = [{email = "dev@example.com"}]\n',
        )
        evs = PrivacyCollector().collect(tmp_path, None)
        pii = evs[0].payload["pii_matches"]
        emails = [m for m in pii if m["pattern_type"] == "email"]
        assert emails == []

    def test_license_file_excluded(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "LICENSE", "Copyright user@example.com 2024\n")
        evs = PrivacyCollector().collect(tmp_path, None)
        pii = evs[0].payload["pii_matches"]
        emails = [m for m in pii if m["pattern_type"] == "email"]
        assert emails == []

    def test_package_json_email_excluded(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "package.json", '{"author": "dev@example.com"}\n')
        evs = PrivacyCollector().collect(tmp_path, None)
        pii = evs[0].payload["pii_matches"]
        emails = [m for m in pii if m["pattern_type"] == "email"]
        assert emails == []

    def test_internal_domain_detected(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "app.py", "url = 'https://api.internal.acme'\n")
        evs = PrivacyCollector().collect(tmp_path, None)
        refs = evs[0].payload["internal_references"]
        assert any(m["pattern_type"] == "internal_domain" for m in refs)

    def test_internal_ip_detected(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "app.py", "host = '10.0.1.50'\n")
        evs = PrivacyCollector().collect(tmp_path, None)
        refs = evs[0].payload["internal_references"]
        assert any(m["pattern_type"] == "internal_ip" for m in refs)

    def test_google_analytics_detected(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "track.js", "ga('create', 'UA-12345678-1');\n")
        evs = PrivacyCollector().collect(tmp_path, None)
        tracking = evs[0].payload["tracking_ids"]
        assert any(m["pattern_type"] == "google_analytics" for m in tracking)

    def test_tracking_via_env_not_flagged(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "track.py",
            "ga_id = os.environ.get('GA_ID', 'UA-12345678-1')\n",
        )
        evs = PrivacyCollector().collect(tmp_path, None)
        tracking = evs[0].payload["tracking_ids"]
        assert tracking == []

    def test_binary_files_skipped(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "image.png", "ssn = '123-45-6789'\n")
        evs = PrivacyCollector().collect(tmp_path, None)
        assert evs[0].payload["files_scanned"] == 0
        assert evs[0].payload["pii_matches"] == []

    def test_git_dir_skipped(self, tmp_path: Path) -> None:
        _write_file(tmp_path, ".git/config", "email = dev@example.com\n")
        _write_file(tmp_path, "main.py", "x = 1\n")
        evs = PrivacyCollector().collect(tmp_path, None)
        assert evs[0].payload["files_scanned"] == 1

    def test_snippet_truncation(self, tmp_path: Path) -> None:
        long_line = "email = 'a" + "b" * 100 + "@example.com'\n"
        _write_file(tmp_path, "long.py", long_line)
        evs = PrivacyCollector().collect(tmp_path, None)
        for m in evs[0].payload["pii_matches"]:
            assert len(m["snippet"]) <= 43  # 40 + "..."

    def test_empty_directory(self, tmp_path: Path) -> None:
        evs = PrivacyCollector().collect(tmp_path, None)
        assert evs[0].payload["files_scanned"] == 0
        assert evs[0].payload["pii_matches"] == []
        assert evs[0].payload["internal_references"] == []
        assert evs[0].payload["tracking_ids"] == []

    def test_internal_refs_excluded_in_config_files(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "pyproject.toml",
            "url = 'https://api.internal'\n",
        )
        evs = PrivacyCollector().collect(tmp_path, None)
        refs = evs[0].payload["internal_references"]
        assert refs == []

    def test_facebook_pixel_detected(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "pixel.js", "fbq('init', '1234567890');\n")
        evs = PrivacyCollector().collect(tmp_path, None)
        tracking = evs[0].payload["tracking_ids"]
        assert any(m["pattern_type"] == "facebook_pixel" for m in tracking)

    def test_segment_write_key_detected(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "analytics.js",
            "writeKey: 'abcdefghijklmnopqrstuvwx'\n",
        )
        evs = PrivacyCollector().collect(tmp_path, None)
        tracking = evs[0].payload["tracking_ids"]
        assert any(m["pattern_type"] == "segment_write_key" for m in tracking)

    def test_mixpanel_token_detected(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "mp.js",
            "mixpanel.init('aabbccddee11223344556677');\n",
        )
        evs = PrivacyCollector().collect(tmp_path, None)
        tracking = evs[0].payload["tracking_ids"]
        assert any(m["pattern_type"] == "mixpanel_token" for m in tracking)

    def test_node_modules_skipped(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "node_modules/pkg/index.js",
            "email = 'a@b.com'\n",
        )
        _write_file(tmp_path, "app.py", "x = 1\n")
        evs = PrivacyCollector().collect(tmp_path, None)
        assert evs[0].payload["files_scanned"] == 1
        assert evs[0].payload["pii_matches"] == []


# ---------------------------------------------------------------------------
# HYG-PRV-001: PII Patterns Rule
# ---------------------------------------------------------------------------


class TestPiiPatternsRule:
    def test_skip_on_no_evidence(self) -> None:
        rule = PiiPatternsRule()
        result = rule.evaluate([], None)
        assert result.skipped is True

    def test_green_when_clean(self) -> None:
        rule = PiiPatternsRule()
        result = rule.evaluate(_make_evidence(), None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_red_for_ssn(self) -> None:
        rule = PiiPatternsRule()
        ev = _make_evidence(pii=[_match(pattern_type="ssn")])
        result = rule.evaluate(ev, None)
        reds = [f for f in result.findings if f.rag == "red"]
        assert len(reds) == 1
        assert "ssn" in reds[0].summary

    def test_red_for_credit_card(self) -> None:
        rule = PiiPatternsRule()
        ev = _make_evidence(pii=[_match(pattern_type="credit_card")])
        result = rule.evaluate(ev, None)
        reds = [f for f in result.findings if f.rag == "red"]
        assert len(reds) == 1

    def test_amber_for_email(self) -> None:
        rule = PiiPatternsRule()
        ev = _make_evidence(pii=[_match(pattern_type="email")])
        result = rule.evaluate(ev, None)
        ambers = [f for f in result.findings if f.rag == "amber"]
        assert len(ambers) == 1

    def test_amber_for_phone(self) -> None:
        rule = PiiPatternsRule()
        ev = _make_evidence(pii=[_match(pattern_type="phone")])
        result = rule.evaluate(ev, None)
        ambers = [f for f in result.findings if f.rag == "amber"]
        assert len(ambers) == 1

    def test_red_and_amber_together(self) -> None:
        rule = PiiPatternsRule()
        ev = _make_evidence(
            pii=[
                _match(pattern_type="ssn"),
                _match(pattern_type="email"),
            ]
        )
        result = rule.evaluate(ev, None)
        rags = {f.rag for f in result.findings}
        assert rags == {"red", "amber"}

    def test_confidence_value(self) -> None:
        rule = PiiPatternsRule()
        result = rule.evaluate(_make_evidence(), None)
        assert result.findings[0].confidence == 0.7


# ---------------------------------------------------------------------------
# HYG-PRV-002: Internal References Rule
# ---------------------------------------------------------------------------


class TestInternalRefsRule:
    def test_skip_on_no_evidence(self) -> None:
        rule = InternalRefsRule()
        result = rule.evaluate([], None)
        assert result.skipped is True

    def test_green_when_clean(self) -> None:
        rule = InternalRefsRule()
        result = rule.evaluate(_make_evidence(), None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_amber_for_internal_domain(self) -> None:
        rule = InternalRefsRule()
        ev = _make_evidence(internal=[_match(pattern_type="internal_domain")])
        result = rule.evaluate(ev, None)
        assert result.findings[0].rag == "amber"

    def test_amber_for_internal_ip(self) -> None:
        rule = InternalRefsRule()
        ev = _make_evidence(internal=[_match(pattern_type="internal_ip")])
        result = rule.evaluate(ev, None)
        assert result.findings[0].rag == "amber"

    def test_confidence_value(self) -> None:
        rule = InternalRefsRule()
        result = rule.evaluate(_make_evidence(), None)
        assert result.findings[0].confidence == 0.8


# ---------------------------------------------------------------------------
# HYG-PRV-003: Tracking IDs Rule
# ---------------------------------------------------------------------------


class TestTrackingIdsRule:
    def test_skip_on_no_evidence(self) -> None:
        rule = TrackingIdsRule()
        result = rule.evaluate([], None)
        assert result.skipped is True

    def test_green_when_clean(self) -> None:
        rule = TrackingIdsRule()
        result = rule.evaluate(_make_evidence(), None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_amber_for_google_analytics(self) -> None:
        rule = TrackingIdsRule()
        ev = _make_evidence(tracking=[_match(pattern_type="google_analytics")])
        result = rule.evaluate(ev, None)
        assert result.findings[0].rag == "amber"

    def test_amber_for_facebook_pixel(self) -> None:
        rule = TrackingIdsRule()
        ev = _make_evidence(tracking=[_match(pattern_type="facebook_pixel")])
        result = rule.evaluate(ev, None)
        assert result.findings[0].rag == "amber"

    def test_confidence_value(self) -> None:
        rule = TrackingIdsRule()
        result = rule.evaluate(_make_evidence(), None)
        assert result.findings[0].confidence == 0.9
