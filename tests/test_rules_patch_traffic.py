"""Tests for PATCH-TRAFFIC rules (001, 002, 003)."""

from __future__ import annotations

import pytest

from nfr_review.models import Evidence
from nfr_review.rules.patch_traffic import (
    ConnectionDrainingRule,
    FailoverDocumentationRule,
    ProgressiveTrafficShiftingRule,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mesh_evidence(kind: str, payload: dict, locator: str = "test.yaml:svc") -> Evidence:
    return Evidence(
        collector_name="service-mesh",
        collector_version="0.1.0",
        locator=locator,
        kind=kind,
        payload=payload,
    )


def _summary_evidence(vs: int = 0, dr: int = 0, rollouts: int = 0, at: int = 0) -> Evidence:
    return Evidence(
        collector_name="service-mesh",
        collector_version="0.1.0",
        locator=".",
        kind="service-mesh-summary",
        payload={
            "virtual_services": vs,
            "destination_rules": dr,
            "rollouts": rollouts,
            "analysis_templates": at,
            "files_parsed": vs + dr + rollouts + at,
            "files_failed": 0,
        },
    )


def _repo_structure_evidence(
    top_level_files: list[str] | None = None,
    top_level_dirs: list[str] | None = None,
) -> Evidence:
    return Evidence(
        collector_name="repo-structure",
        collector_version="0.1.0",
        locator=".",
        kind="repo-structure-summary",
        payload={
            "top_level_files": top_level_files or [],
            "top_level_dirs": top_level_dirs or [],
        },
    )


# ===========================================================================
# PATCH-TRAFFIC-001: Progressive traffic shifting
# ===========================================================================


class TestTraffic001:
    rule = ProgressiveTrafficShiftingRule()

    def test_skipped_when_no_service_mesh(self):
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert "no service-mesh" in result.skip_reason

    def test_vs_with_weighted_routing_green(self):
        ev = [
            _mesh_evidence(
                "service-mesh-virtual-service",
                {
                    "name": "reviews-route",
                    "has_weighted_routing": True,
                    "http_routes": [
                        {"destinations": [{"host": "reviews", "subset": "v1", "weight": 80}]}
                    ],
                },
            ),
            _summary_evidence(vs=1),
        ]
        result = self.rule.evaluate(ev, None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert "weighted" in result.findings[0].summary.lower()

    def test_vs_without_weighted_routing_amber(self):
        ev = [
            _mesh_evidence(
                "service-mesh-virtual-service",
                {
                    "name": "reviews-route",
                    "has_weighted_routing": False,
                    "http_routes": [
                        {"destinations": [{"host": "reviews", "subset": "v1", "weight": None}]}
                    ],
                },
            ),
            _summary_evidence(vs=1),
        ]
        result = self.rule.evaluate(ev, None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"

    def test_rollout_with_canary_steps_green(self):
        ev = [
            _mesh_evidence(
                "service-mesh-rollout",
                {
                    "name": "reviews-rollout",
                    "strategy_type": "canary",
                    "canary_steps": [
                        {"setWeight": 20},
                        {"pause": {"duration": "60s"}},
                        {"setWeight": 80},
                    ],
                },
            ),
            _summary_evidence(rollouts=1),
        ]
        result = self.rule.evaluate(ev, None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert "3 steps" in result.findings[0].summary

    def test_rollout_canary_no_steps_amber(self):
        ev = [
            _mesh_evidence(
                "service-mesh-rollout",
                {
                    "name": "reviews-rollout",
                    "strategy_type": "canary",
                    "canary_steps": [],
                },
            ),
            _summary_evidence(rollouts=1),
        ]
        result = self.rule.evaluate(ev, None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"

    def test_rollout_blue_green_no_finding(self):
        """blueGreen strategy doesn't produce traffic-shifting findings."""
        ev = [
            _mesh_evidence(
                "service-mesh-rollout",
                {
                    "name": "reviews-rollout",
                    "strategy_type": "blueGreen",
                    "canary_steps": None,
                },
            ),
            _summary_evidence(rollouts=1),
        ]
        result = self.rule.evaluate(ev, None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_both_vs_and_rollout(self):
        ev = [
            _mesh_evidence(
                "service-mesh-virtual-service",
                {"name": "svc", "has_weighted_routing": True, "http_routes": []},
                locator="vs.yaml:svc",
            ),
            _mesh_evidence(
                "service-mesh-rollout",
                {
                    "name": "rollout",
                    "strategy_type": "canary",
                    "canary_steps": [{"setWeight": 50}],
                },
                locator="rollout.yaml:rollout",
            ),
            _summary_evidence(vs=1, rollouts=1),
        ]
        result = self.rule.evaluate(ev, None)
        assert len(result.findings) == 2
        assert all(f.rag == "green" for f in result.findings)

    def test_no_vs_or_rollout_info(self):
        ev = [_summary_evidence()]
        result = self.rule.evaluate(ev, None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert "not applicable" in result.findings[0].summary.lower()

    def test_rollout_canary_steps_none_treated_as_empty(self):
        ev = [
            _mesh_evidence(
                "service-mesh-rollout",
                {
                    "name": "r",
                    "strategy_type": "canary",
                    "canary_steps": None,
                },
            ),
            _summary_evidence(rollouts=1),
        ]
        result = self.rule.evaluate(ev, None)
        assert result.findings[0].rag == "amber"

    def test_finding_metadata(self):
        ev = [
            _mesh_evidence(
                "service-mesh-virtual-service",
                {"name": "svc", "has_weighted_routing": True, "http_routes": []},
            ),
            _summary_evidence(vs=1),
        ]
        result = self.rule.evaluate(ev, None)
        f = result.findings[0]
        assert f.rule_id == "PATCH-TRAFFIC-001"
        assert f.pattern_tag == "patch-traffic-shifting"
        assert f.severity == "info"

    def test_amber_finding_metadata(self):
        ev = [
            _mesh_evidence(
                "service-mesh-virtual-service",
                {"name": "svc", "has_weighted_routing": False, "http_routes": []},
            ),
            _summary_evidence(vs=1),
        ]
        result = self.rule.evaluate(ev, None)
        f = result.findings[0]
        assert f.rule_id == "PATCH-TRAFFIC-001"
        assert f.pattern_tag == "patch-traffic-shifting"
        assert f.severity == "medium"


# ===========================================================================
# PATCH-TRAFFIC-002: Failover documentation
# ===========================================================================


class TestTraffic002:
    rule = FailoverDocumentationRule()

    def test_skipped_when_no_repo_structure(self):
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert "repo-structure" in result.skip_reason

    def test_failover_md_found_green(self):
        ev = [_repo_structure_evidence(top_level_files=["failover.md", "README.md"])]
        result = self.rule.evaluate(ev, None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert "failover.md" in result.findings[0].summary

    def test_dr_runbook_found_green(self):
        ev = [_repo_structure_evidence(top_level_files=["DR-RUNBOOK.md"])]
        result = self.rule.evaluate(ev, None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_failover_dir_found_green(self):
        ev = [_repo_structure_evidence(top_level_dirs=["failover"])]
        result = self.rule.evaluate(ev, None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_disaster_recovery_dir_green(self):
        ev = [_repo_structure_evidence(top_level_dirs=["disaster-recovery"])]
        result = self.rule.evaluate(ev, None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_dr_runbooks_dir_green(self):
        ev = [_repo_structure_evidence(top_level_dirs=["dr-runbooks"])]
        result = self.rule.evaluate(ev, None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_no_failover_docs_amber(self):
        ev = [_repo_structure_evidence(top_level_files=["README.md"])]
        result = self.rule.evaluate(ev, None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert "failover" in result.findings[0].summary.lower()

    def test_multiple_matches(self):
        ev = [
            _repo_structure_evidence(
                top_level_files=["failover.md", "disaster-recovery.md"],
                top_level_dirs=["dr-runbooks"],
            )
        ]
        result = self.rule.evaluate(ev, None)
        assert len(result.findings) == 3
        assert all(f.rag == "green" for f in result.findings)

    def test_case_insensitive_match(self):
        ev = [_repo_structure_evidence(top_level_files=["FAILOVER.md"])]
        result = self.rule.evaluate(ev, None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_disaster_recovery_md_green(self):
        ev = [_repo_structure_evidence(top_level_files=["disaster-recovery.md"])]
        result = self.rule.evaluate(ev, None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_finding_metadata(self):
        ev = [_repo_structure_evidence(top_level_files=["failover.md"])]
        result = self.rule.evaluate(ev, None)
        f = result.findings[0]
        assert f.rule_id == "PATCH-TRAFFIC-002"
        assert f.pattern_tag == "patch-traffic-failover-docs"
        assert f.severity == "info"

    def test_amber_finding_metadata(self):
        ev = [_repo_structure_evidence(top_level_files=["README.md"])]
        result = self.rule.evaluate(ev, None)
        f = result.findings[0]
        assert f.rule_id == "PATCH-TRAFFIC-002"
        assert f.pattern_tag == "patch-traffic-failover-docs"
        assert f.severity == "medium"


# ===========================================================================
# PATCH-TRAFFIC-003: Connection draining
# ===========================================================================


class TestTraffic003:
    rule = ConnectionDrainingRule()

    def test_skipped_when_no_service_mesh(self):
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert "no service-mesh" in result.skip_reason

    def test_dr_with_connection_pool_green(self):
        ev = [
            _mesh_evidence(
                "service-mesh-destination-rule",
                {
                    "name": "reviews",
                    "has_connection_pool": True,
                    "connection_pool": {
                        "tcp": {"maxConnections": 100},
                        "http": {"http1MaxPendingRequests": 100},
                    },
                },
            ),
            _summary_evidence(dr=1),
        ]
        result = self.rule.evaluate(ev, None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert "connectionPool" in result.findings[0].summary

    def test_dr_without_connection_pool_amber(self):
        ev = [
            _mesh_evidence(
                "service-mesh-destination-rule",
                {
                    "name": "reviews",
                    "has_connection_pool": False,
                    "connection_pool": None,
                },
            ),
            _summary_evidence(dr=1),
        ]
        result = self.rule.evaluate(ev, None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert "draining" in result.findings[0].summary.lower()

    def test_no_destination_rules_info(self):
        ev = [_summary_evidence()]
        result = self.rule.evaluate(ev, None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert "not applicable" in result.findings[0].summary.lower()

    def test_multiple_drs_mixed(self):
        ev = [
            _mesh_evidence(
                "service-mesh-destination-rule",
                {"name": "svc-a", "has_connection_pool": True, "connection_pool": {}},
                locator="dr1.yaml:svc-a",
            ),
            _mesh_evidence(
                "service-mesh-destination-rule",
                {"name": "svc-b", "has_connection_pool": False, "connection_pool": None},
                locator="dr2.yaml:svc-b",
            ),
            _summary_evidence(dr=2),
        ]
        result = self.rule.evaluate(ev, None)
        assert len(result.findings) == 2
        rags = {f.rag for f in result.findings}
        assert "green" in rags
        assert "amber" in rags

    def test_finding_metadata(self):
        ev = [
            _mesh_evidence(
                "service-mesh-destination-rule",
                {"name": "svc", "has_connection_pool": True, "connection_pool": {}},
            ),
            _summary_evidence(dr=1),
        ]
        result = self.rule.evaluate(ev, None)
        f = result.findings[0]
        assert f.rule_id == "PATCH-TRAFFIC-003"
        assert f.pattern_tag == "patch-traffic-drain"
        assert f.severity == "info"

    def test_amber_finding_metadata(self):
        ev = [
            _mesh_evidence(
                "service-mesh-destination-rule",
                {"name": "svc", "has_connection_pool": False, "connection_pool": None},
            ),
            _summary_evidence(dr=1),
        ]
        result = self.rule.evaluate(ev, None)
        f = result.findings[0]
        assert f.rule_id == "PATCH-TRAFFIC-003"
        assert f.pattern_tag == "patch-traffic-drain"
        assert f.severity == "medium"


# ===========================================================================
# Registration
# ===========================================================================


class TestRegistration:
    def test_rules_registered(self):
        from nfr_review.registry import rule_registry

        assert "PATCH-TRAFFIC-001" in rule_registry
        assert "PATCH-TRAFFIC-002" in rule_registry
        assert "PATCH-TRAFFIC-003" in rule_registry

    def test_rule_ids(self):
        assert ProgressiveTrafficShiftingRule().id == "PATCH-TRAFFIC-001"
        assert FailoverDocumentationRule().id == "PATCH-TRAFFIC-002"
        assert ConnectionDrainingRule().id == "PATCH-TRAFFIC-003"

    def test_required_collectors(self):
        assert ProgressiveTrafficShiftingRule().required_collectors == ["service-mesh"]
        assert FailoverDocumentationRule().required_collectors == ["repo-structure"]
        assert ConnectionDrainingRule().required_collectors == ["service-mesh"]


# ===========================================================================
# Integration with fixture repos
# ===========================================================================


class TestFixtureIntegration:
    """Run the rules against evidence from the actual fixture repos."""

    @pytest.fixture()
    def sample_repo_evidence(self, tmp_path):
        """Collect evidence from service-mesh-sample-repo fixture."""
        import shutil
        from pathlib import Path

        fixture = Path(__file__).parent / "fixtures" / "service-mesh-sample-repo"
        target = tmp_path / "repo"
        shutil.copytree(fixture, target)

        from nfr_review.collectors.service_mesh import ServiceMeshCollector

        collector = ServiceMeshCollector()
        return collector.collect(target, None)

    @pytest.fixture()
    def good_repo_evidence(self, tmp_path):
        """Collect evidence from service-mesh-good-repo fixture."""
        import shutil
        from pathlib import Path

        fixture = Path(__file__).parent / "fixtures" / "service-mesh-good-repo"
        target = tmp_path / "repo"
        shutil.copytree(fixture, target)

        from nfr_review.collectors.service_mesh import ServiceMeshCollector

        collector = ServiceMeshCollector()
        return collector.collect(target, None)

    def test_traffic_001_sample_repo(self, sample_repo_evidence):
        rule = ProgressiveTrafficShiftingRule()
        result = rule.evaluate(sample_repo_evidence, None)
        assert not result.skipped
        greens = [f for f in result.findings if f.rag == "green"]
        assert len(greens) >= 1

    def test_traffic_001_good_repo(self, good_repo_evidence):
        rule = ProgressiveTrafficShiftingRule()
        result = rule.evaluate(good_repo_evidence, None)
        assert not result.skipped
        greens = [f for f in result.findings if f.rag == "green"]
        assert len(greens) >= 2

    def test_traffic_003_sample_repo_no_pool(self, sample_repo_evidence):
        """Sample repo DR has no connectionPool."""
        rule = ConnectionDrainingRule()
        result = rule.evaluate(sample_repo_evidence, None)
        assert not result.skipped
        ambers = [f for f in result.findings if f.rag == "amber"]
        assert len(ambers) >= 1

    def test_traffic_003_good_repo_has_pool(self, good_repo_evidence):
        """Good repo DR has connectionPool configured."""
        rule = ConnectionDrainingRule()
        result = rule.evaluate(good_repo_evidence, None)
        assert not result.skipped
        greens = [f for f in result.findings if f.rag == "green"]
        assert len(greens) >= 1
