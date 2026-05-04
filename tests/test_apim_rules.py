"""Tests for APIM Band 1 rules -- positive, negative, and skip fixtures."""

from __future__ import annotations

import pytest

from nfr_review.models import Evidence, RuleResult
from nfr_review.rules.apim_auth import ApimAuthPolicyMissingRule
from nfr_review.rules.apim_backend_url import ApimHardcodedBackendUrlRule
from nfr_review.rules.apim_rate_limit import ApimRateLimitMissingRule


def _apim_evidence(payload: dict) -> Evidence:
    return Evidence(
        collector_name="apim-policy",
        collector_version="0.1.0",
        locator=payload.get("file_path", "policies/test.xml"),
        kind="apim-policy",
        payload=payload,
    )


# ---------------------------------------------------------------------------
# apim-rate-limit-missing
# ---------------------------------------------------------------------------


class TestApimRateLimitMissingRule:
    def setup_method(self) -> None:
        self.rule = ApimRateLimitMissingRule()

    def test_no_evidence_skipped(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert result.skip_reason == "no apim-policy evidence available"

    def test_missing_rate_limit_red(self) -> None:
        ev = _apim_evidence({
            "file_path": "policies/bad-policy.xml",
            "has_rate_limit": False,
            "has_auth_policy": False,
            "backend_urls": ["https://api.example.com/v1"],
            "uses_named_values": False,
            "inbound_policies": ["base"],
            "outbound_policies": ["base"],
        })
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "red"
        assert result.findings[0].severity == "high"
        assert result.findings[0].pattern_tag == "apim-rate-limit"

    def test_rate_limit_present_green(self) -> None:
        ev = _apim_evidence({
            "file_path": "policies/good-policy.xml",
            "has_rate_limit": True,
            "has_auth_policy": True,
            "backend_urls": ["{{backend-url}}"],
            "uses_named_values": True,
            "inbound_policies": ["rate-limit", "validate-jwt", "base"],
            "outbound_policies": ["base"],
        })
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"


# ---------------------------------------------------------------------------
# apim-auth-policy-missing
# ---------------------------------------------------------------------------


class TestApimAuthPolicyMissingRule:
    def setup_method(self) -> None:
        self.rule = ApimAuthPolicyMissingRule()

    def test_no_evidence_skipped(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert result.skip_reason == "no apim-policy evidence available"

    def test_missing_auth_red(self) -> None:
        ev = _apim_evidence({
            "file_path": "policies/bad-policy.xml",
            "has_rate_limit": False,
            "has_auth_policy": False,
            "backend_urls": ["https://api.example.com/v1"],
            "uses_named_values": False,
            "inbound_policies": ["base"],
            "outbound_policies": ["base"],
        })
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "red"
        assert result.findings[0].severity == "critical"
        assert result.findings[0].pattern_tag == "apim-auth-policy"

    def test_auth_present_green(self) -> None:
        ev = _apim_evidence({
            "file_path": "policies/good-policy.xml",
            "has_rate_limit": True,
            "has_auth_policy": True,
            "backend_urls": ["{{backend-url}}"],
            "uses_named_values": True,
            "inbound_policies": ["rate-limit", "validate-jwt", "base"],
            "outbound_policies": ["base"],
        })
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"


# ---------------------------------------------------------------------------
# apim-hardcoded-backend-url
# ---------------------------------------------------------------------------


class TestApimHardcodedBackendUrlRule:
    def setup_method(self) -> None:
        self.rule = ApimHardcodedBackendUrlRule()

    def test_no_evidence_skipped(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert result.skip_reason == "no apim-policy evidence available"

    def test_hardcoded_url_amber(self) -> None:
        ev = _apim_evidence({
            "file_path": "policies/bad-policy.xml",
            "has_rate_limit": False,
            "has_auth_policy": False,
            "backend_urls": ["https://api.example.com/v1"],
            "uses_named_values": False,
            "inbound_policies": ["base"],
            "outbound_policies": ["base"],
        })
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert result.findings[0].severity == "medium"
        assert result.findings[0].pattern_tag == "apim-backend-url"
        assert "https://api.example.com/v1" in result.findings[0].summary

    def test_named_value_url_green(self) -> None:
        ev = _apim_evidence({
            "file_path": "policies/good-policy.xml",
            "has_rate_limit": True,
            "has_auth_policy": True,
            "backend_urls": ["{{backend-url}}"],
            "uses_named_values": True,
            "inbound_policies": ["rate-limit", "validate-jwt", "base"],
            "outbound_policies": ["base"],
        })
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_no_backend_urls_green(self) -> None:
        ev = _apim_evidence({
            "file_path": "policies/minimal.xml",
            "has_rate_limit": False,
            "has_auth_policy": False,
            "backend_urls": [],
            "uses_named_values": False,
            "inbound_policies": ["base"],
            "outbound_policies": ["base"],
        })
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        # No backend URLs means nothing to flag
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_mixed_urls_amber(self) -> None:
        ev = _apim_evidence({
            "file_path": "policies/mixed.xml",
            "has_rate_limit": True,
            "has_auth_policy": True,
            "backend_urls": ["{{backend-url}}", "https://hardcoded.example.com"],
            "uses_named_values": True,
            "inbound_policies": ["rate-limit", "validate-jwt", "base"],
            "outbound_policies": ["base"],
        })
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"


# ---------------------------------------------------------------------------
# Cross-cutting: verify all rules follow protocol
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rule_class",
    [
        ApimRateLimitMissingRule,
        ApimAuthPolicyMissingRule,
        ApimHardcodedBackendUrlRule,
    ],
)
def test_rule_protocol_compliance(rule_class: type) -> None:
    rule = rule_class()
    assert hasattr(rule, "id")
    assert hasattr(rule, "band")
    assert hasattr(rule, "required_collectors")
    assert hasattr(rule, "required_tech")
    assert rule.band == 1
    assert rule.required_collectors == ["apim-policy"]
    assert rule.required_tech == ["apim"]
    result = rule.evaluate([], None)
    assert isinstance(result, RuleResult)
    assert result.skipped is True


@pytest.mark.parametrize(
    "rule_class",
    [
        ApimRateLimitMissingRule,
        ApimAuthPolicyMissingRule,
        ApimHardcodedBackendUrlRule,
    ],
)
def test_finding_has_all_r007_fields(rule_class: type) -> None:
    """Verify that when a rule fires, findings have all 10 R007 fields."""
    ev = _apim_evidence({
        "file_path": "policies/test.xml",
        "has_rate_limit": False,
        "has_auth_policy": False,
        "backend_urls": ["https://api.example.com/v1"],
        "uses_named_values": False,
        "inbound_policies": ["base"],
        "outbound_policies": ["base"],
    })
    rule = rule_class()
    result = rule.evaluate([ev], None)
    assert not result.skipped
    for finding in result.findings:
        assert finding.rule_id
        assert finding.rag in ("red", "amber", "green")
        assert finding.severity
        assert finding.summary
        assert finding.recommendation
        assert finding.evidence_locator
        assert finding.collector_name == "apim-policy"
        assert finding.collector_version == "0.1.0"
        assert 0.0 <= finding.confidence <= 1.0
        assert finding.pattern_tag
