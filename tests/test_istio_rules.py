"""Tests for Istio NFR rules: mtls-strict, traffic-policy, circuit-breaker."""

from __future__ import annotations

import importlib
from typing import Any

from nfr_review.models import Evidence
from nfr_review.registry import rule_registry
from nfr_review.rules.istio_circuit_breaker import IstioCircuitBreakerRule
from nfr_review.rules.istio_mtls_strict import IstioMtlsStrictRule
from nfr_review.rules.istio_traffic_policy import IstioTrafficPolicyRule


def _make_evidence(resources: list[dict[str, Any]]) -> list[Evidence]:
    return [
        Evidence(
            collector_name="istio",
            collector_version="0.1.0",
            locator="peer-authentication.yaml",
            kind="istio-analysis",
            payload={
                "file_path": "peer-authentication.yaml",
                "resources": resources,
            },
        )
    ]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_mtls_strict_registered(self) -> None:
        import nfr_review.rules.istio_mtls_strict

        importlib.reload(nfr_review.rules.istio_mtls_strict)
        assert "istio-mtls-strict" in rule_registry

    def test_traffic_policy_registered(self) -> None:
        import nfr_review.rules.istio_traffic_policy

        importlib.reload(nfr_review.rules.istio_traffic_policy)
        assert "istio-traffic-policy" in rule_registry

    def test_circuit_breaker_registered(self) -> None:
        import nfr_review.rules.istio_circuit_breaker

        importlib.reload(nfr_review.rules.istio_circuit_breaker)
        assert "istio-circuit-breaker" in rule_registry


# ---------------------------------------------------------------------------
# Rule attributes
# ---------------------------------------------------------------------------


class TestRuleAttributes:
    def test_mtls_strict_attributes(self) -> None:
        rule = IstioMtlsStrictRule()
        assert rule.id == "istio-mtls-strict"
        assert rule.band == 1
        assert rule.required_collectors == ["istio"]
        assert rule.required_tech == ["istio"]

    def test_traffic_policy_attributes(self) -> None:
        rule = IstioTrafficPolicyRule()
        assert rule.id == "istio-traffic-policy"
        assert rule.band == 1
        assert rule.required_collectors == ["istio"]
        assert rule.required_tech == ["istio"]

    def test_circuit_breaker_attributes(self) -> None:
        rule = IstioCircuitBreakerRule()
        assert rule.id == "istio-circuit-breaker"
        assert rule.band == 1
        assert rule.required_collectors == ["istio"]
        assert rule.required_tech == ["istio"]


# ---------------------------------------------------------------------------
# IstioMtlsStrictRule
# ---------------------------------------------------------------------------


class TestIstioMtlsStrict:
    def setup_method(self) -> None:
        self.rule = IstioMtlsStrictRule()

    def test_skip_no_evidence(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert "no istio-analysis evidence" in result.skip_reason

    def test_skip_wrong_collector(self) -> None:
        evidence = [
            Evidence(
                collector_name="terraform",
                collector_version="0.1.0",
                locator="main.tf",
                kind="terraform-analysis",
                payload={},
            )
        ]
        result = self.rule.evaluate(evidence, None)
        assert result.skipped is True

    def test_red_no_peer_authentication(self) -> None:
        evidence = _make_evidence(
            [
                {"kind": "VirtualService", "spec": {}, "name": "vs1"},
            ]
        )
        result = self.rule.evaluate(evidence, None)
        assert not result.skipped
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "red"
        assert f.severity == "high"
        assert "mTLS" in f.summary
        assert f.rule_id == "istio-mtls-strict"
        assert f.pattern_tag == "istio-mtls-strict"

    def test_red_permissive_mode(self) -> None:
        evidence = _make_evidence(
            [
                {
                    "kind": "PeerAuthentication",
                    "name": "default",
                    "spec": {"mtls": {"mode": "PERMISSIVE"}},
                },
            ]
        )
        result = self.rule.evaluate(evidence, None)
        assert not result.skipped
        assert result.findings[0].rag == "red"
        assert "STRICT" in result.findings[0].recommendation

    def test_red_disable_mode(self) -> None:
        evidence = _make_evidence(
            [
                {
                    "kind": "PeerAuthentication",
                    "name": "default",
                    "spec": {"mtls": {"mode": "DISABLE"}},
                },
            ]
        )
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "red"

    def test_red_missing_mtls_spec(self) -> None:
        evidence = _make_evidence(
            [
                {
                    "kind": "PeerAuthentication",
                    "name": "default",
                    "spec": {},
                },
            ]
        )
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "red"

    def test_green_strict_mode(self) -> None:
        evidence = _make_evidence(
            [
                {
                    "kind": "PeerAuthentication",
                    "name": "default",
                    "spec": {"mtls": {"mode": "STRICT"}},
                },
            ]
        )
        result = self.rule.evaluate(evidence, None)
        assert not result.skipped
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "green"
        assert f.severity == "info"
        assert "STRICT" in f.summary

    def test_green_multiple_with_one_strict(self) -> None:
        evidence = _make_evidence(
            [
                {
                    "kind": "PeerAuthentication",
                    "name": "permissive",
                    "spec": {"mtls": {"mode": "PERMISSIVE"}},
                },
                {
                    "kind": "PeerAuthentication",
                    "name": "strict",
                    "spec": {"mtls": {"mode": "STRICT"}},
                },
            ]
        )
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "green"

    def test_finding_fields_complete(self) -> None:
        evidence = _make_evidence(
            [
                {
                    "kind": "PeerAuthentication",
                    "name": "default",
                    "spec": {"mtls": {"mode": "PERMISSIVE"}},
                },
            ]
        )
        result = self.rule.evaluate(evidence, None)
        f = result.findings[0]
        assert f.collector_name == "istio"
        assert f.collector_version == "0.1.0"
        assert f.confidence == 0.9
        assert f.evidence_locator == "peer-authentication.yaml"


# ---------------------------------------------------------------------------
# IstioTrafficPolicyRule
# ---------------------------------------------------------------------------


class TestIstioTrafficPolicy:
    def setup_method(self) -> None:
        self.rule = IstioTrafficPolicyRule()

    def test_skip_no_evidence(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert "no istio-analysis evidence" in result.skip_reason

    def test_skip_no_destination_rules(self) -> None:
        evidence = _make_evidence(
            [
                {"kind": "VirtualService", "spec": {}, "name": "vs1"},
            ]
        )
        result = self.rule.evaluate(evidence, None)
        assert result.skipped is True
        assert "no DestinationRule" in result.skip_reason

    def test_amber_missing_traffic_policy(self) -> None:
        evidence = _make_evidence(
            [
                {
                    "kind": "DestinationRule",
                    "name": "reviews",
                    "spec": {"host": "reviews.default.svc.cluster.local"},
                },
            ]
        )
        result = self.rule.evaluate(evidence, None)
        assert not result.skipped
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "amber"
        assert f.severity == "medium"
        assert "reviews" in f.summary
        assert "connectionPool" in f.recommendation

    def test_amber_empty_traffic_policy(self) -> None:
        evidence = _make_evidence(
            [
                {
                    "kind": "DestinationRule",
                    "name": "reviews",
                    "spec": {"host": "reviews", "trafficPolicy": {}},
                },
            ]
        )
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "amber"

    def test_amber_traffic_policy_no_connection_pool(self) -> None:
        evidence = _make_evidence(
            [
                {
                    "kind": "DestinationRule",
                    "name": "reviews",
                    "spec": {
                        "host": "reviews",
                        "trafficPolicy": {"loadBalancer": {"simple": "ROUND_ROBIN"}},
                    },
                },
            ]
        )
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "amber"

    def test_green_with_connection_pool(self) -> None:
        evidence = _make_evidence(
            [
                {
                    "kind": "DestinationRule",
                    "name": "reviews",
                    "spec": {
                        "host": "reviews",
                        "trafficPolicy": {
                            "connectionPool": {
                                "tcp": {"maxConnections": 100},
                            },
                        },
                    },
                },
            ]
        )
        result = self.rule.evaluate(evidence, None)
        assert not result.skipped
        assert result.findings[0].rag == "green"
        assert result.findings[0].severity == "info"

    def test_amber_partial_compliance(self) -> None:
        evidence = _make_evidence(
            [
                {
                    "kind": "DestinationRule",
                    "name": "good-dr",
                    "spec": {
                        "host": "good",
                        "trafficPolicy": {"connectionPool": {"tcp": {"maxConnections": 50}}},
                    },
                },
                {
                    "kind": "DestinationRule",
                    "name": "bad-dr",
                    "spec": {"host": "bad"},
                },
            ]
        )
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "amber"
        assert "bad-dr" in result.findings[0].summary

    def test_finding_fields_complete(self) -> None:
        evidence = _make_evidence(
            [
                {
                    "kind": "DestinationRule",
                    "name": "reviews",
                    "spec": {"host": "reviews"},
                },
            ]
        )
        result = self.rule.evaluate(evidence, None)
        f = result.findings[0]
        assert f.rule_id == "istio-traffic-policy"
        assert f.collector_name == "istio"
        assert f.collector_version == "0.1.0"
        assert f.confidence == 0.85
        assert f.pattern_tag == "istio-traffic-policy"


# ---------------------------------------------------------------------------
# IstioCircuitBreakerRule
# ---------------------------------------------------------------------------


class TestIstioCircuitBreaker:
    def setup_method(self) -> None:
        self.rule = IstioCircuitBreakerRule()

    def test_skip_no_evidence(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert "no istio-analysis evidence" in result.skip_reason

    def test_skip_no_destination_rules(self) -> None:
        evidence = _make_evidence(
            [
                {"kind": "PeerAuthentication", "spec": {}, "name": "pa1"},
            ]
        )
        result = self.rule.evaluate(evidence, None)
        assert result.skipped is True
        assert "no DestinationRule" in result.skip_reason

    def test_amber_no_outlier_detection(self) -> None:
        evidence = _make_evidence(
            [
                {
                    "kind": "DestinationRule",
                    "name": "reviews",
                    "spec": {
                        "host": "reviews",
                        "trafficPolicy": {
                            "connectionPool": {"tcp": {"maxConnections": 100}},
                        },
                    },
                },
            ]
        )
        result = self.rule.evaluate(evidence, None)
        assert not result.skipped
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "amber"
        assert f.severity == "medium"
        assert "circuit breaker" in f.summary.lower() or "outlierDetection" in f.summary
        assert "outlierDetection" in f.recommendation

    def test_amber_empty_traffic_policy(self) -> None:
        evidence = _make_evidence(
            [
                {
                    "kind": "DestinationRule",
                    "name": "reviews",
                    "spec": {"host": "reviews", "trafficPolicy": {}},
                },
            ]
        )
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "amber"

    def test_amber_no_traffic_policy(self) -> None:
        evidence = _make_evidence(
            [
                {
                    "kind": "DestinationRule",
                    "name": "reviews",
                    "spec": {"host": "reviews"},
                },
            ]
        )
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "amber"

    def test_green_with_outlier_detection(self) -> None:
        evidence = _make_evidence(
            [
                {
                    "kind": "DestinationRule",
                    "name": "reviews",
                    "spec": {
                        "host": "reviews",
                        "trafficPolicy": {
                            "outlierDetection": {
                                "consecutive5xxErrors": 5,
                                "interval": "10s",
                                "baseEjectionTime": "30s",
                            },
                        },
                    },
                },
            ]
        )
        result = self.rule.evaluate(evidence, None)
        assert not result.skipped
        assert result.findings[0].rag == "green"
        assert result.findings[0].severity == "info"

    def test_green_one_of_many_has_outlier_detection(self) -> None:
        evidence = _make_evidence(
            [
                {
                    "kind": "DestinationRule",
                    "name": "no-cb",
                    "spec": {"host": "a", "trafficPolicy": {}},
                },
                {
                    "kind": "DestinationRule",
                    "name": "with-cb",
                    "spec": {
                        "host": "b",
                        "trafficPolicy": {
                            "outlierDetection": {"consecutive5xxErrors": 3},
                        },
                    },
                },
            ]
        )
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "green"

    def test_finding_fields_complete(self) -> None:
        evidence = _make_evidence(
            [
                {
                    "kind": "DestinationRule",
                    "name": "reviews",
                    "spec": {"host": "reviews"},
                },
            ]
        )
        result = self.rule.evaluate(evidence, None)
        f = result.findings[0]
        assert f.rule_id == "istio-circuit-breaker"
        assert f.collector_name == "istio"
        assert f.collector_version == "0.1.0"
        assert f.confidence == 0.85
        assert f.pattern_tag == "istio-circuit-breaker"
