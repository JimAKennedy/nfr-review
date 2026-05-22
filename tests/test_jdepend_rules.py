# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for JDepend rules — JDEP-CYCLE, JDEP-INSTABILITY, JDEP-DISTANCE."""

from __future__ import annotations

from nfr_review.models import Evidence
from nfr_review.registry import rule_registry
from nfr_review.rules.jdepend_cycle import JDepCycleRule
from nfr_review.rules.jdepend_distance import JDepDistanceRule
from nfr_review.rules.jdepend_instability import JDepInstabilityRule


def _make_packages_evidence(
    packages: list[dict],
    cycle_groups: list[list[str]] | None = None,
) -> Evidence:
    return Evidence(
        collector_name="jdepend",
        collector_version="0.1.0",
        locator="target/classes",
        kind="jdepend-packages",
        payload={
            "packages": packages,
            "bytecode_dir": "target/classes",
            "cycle_groups": cycle_groups or [],
        },
    )


def _make_skip_evidence(reason: str = "jdepend not installed") -> Evidence:
    return Evidence(
        collector_name="jdepend",
        collector_version="0.1.0",
        locator=".",
        kind="jdepend-skip",
        payload={"reason": reason},
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_cycle_rule_registered(self) -> None:
        assert "JDEP-CYCLE" in rule_registry

    def test_instability_rule_registered(self) -> None:
        assert "JDEP-INSTABILITY" in rule_registry

    def test_distance_rule_registered(self) -> None:
        assert "JDEP-DISTANCE" in rule_registry


# ---------------------------------------------------------------------------
# JDEP-CYCLE
# ---------------------------------------------------------------------------


class TestJDepCycleRule:
    def test_skip_when_no_evidence(self) -> None:
        rule = JDepCycleRule()
        result = rule.evaluate([], None)
        assert result.skipped is True

    def test_skip_when_jdepend_unavailable(self) -> None:
        rule = JDepCycleRule()
        result = rule.evaluate([_make_skip_evidence()], None)
        assert result.skipped is True
        assert "jdepend not installed" in (result.skip_reason or "")

    def test_green_when_no_cycles(self) -> None:
        ev = _make_packages_evidence(
            packages=[
                {"name": "com.example.core", "Ca": 3, "Ce": 2, "A": 0.5, "I": 0.4, "D": 0.1}
            ],
            cycle_groups=[],
        )
        rule = JDepCycleRule()
        result = rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert result.findings[0].pattern_tag == "jdep-cycle-ok"

    def test_red_when_cycle_detected(self) -> None:
        ev = _make_packages_evidence(
            packages=[
                {"name": "com.example.a", "Ca": 1, "Ce": 1, "A": 0.0, "I": 0.5, "D": 0.5},
                {"name": "com.example.b", "Ca": 1, "Ce": 1, "A": 0.0, "I": 0.5, "D": 0.5},
            ],
            cycle_groups=[["com.example.a", "com.example.b"]],
        )
        rule = JDepCycleRule()
        result = rule.evaluate([ev], None)
        assert not result.skipped
        assert any(f.rag == "red" for f in result.findings)
        assert any("cycle" in f.summary.lower() for f in result.findings)
        assert any(f.pattern_tag == "jdep-cycle-detected" for f in result.findings)

    def test_multiple_cycle_groups(self) -> None:
        ev = _make_packages_evidence(
            packages=[],
            cycle_groups=[
                ["com.a", "com.b"],
                ["com.c", "com.d", "com.e"],
            ],
        )
        rule = JDepCycleRule()
        result = rule.evaluate([ev], None)
        red_findings = [f for f in result.findings if f.rag == "red"]
        assert len(red_findings) == 2


# ---------------------------------------------------------------------------
# JDEP-INSTABILITY
# ---------------------------------------------------------------------------


class TestJDepInstabilityRule:
    def test_skip_when_no_evidence(self) -> None:
        rule = JDepInstabilityRule()
        result = rule.evaluate([], None)
        assert result.skipped is True

    def test_skip_when_jdepend_unavailable(self) -> None:
        rule = JDepInstabilityRule()
        result = rule.evaluate([_make_skip_evidence()], None)
        assert result.skipped is True

    def test_green_when_balanced(self) -> None:
        ev = _make_packages_evidence(
            packages=[
                {"name": "com.example.core", "Ca": 5, "Ce": 3, "A": 0.5, "I": 0.4, "D": 0.1},
            ]
        )
        rule = JDepInstabilityRule()
        result = rule.evaluate([ev], None)
        assert not result.skipped
        assert all(f.rag == "green" for f in result.findings)

    def test_amber_when_high_instability_low_abstractness(self) -> None:
        ev = _make_packages_evidence(
            packages=[
                {
                    "name": "com.example.fragile",
                    "Ca": 1,
                    "Ce": 10,
                    "A": 0.1,
                    "I": 0.91,
                    "D": 0.01,
                },
            ]
        )
        rule = JDepInstabilityRule()
        result = rule.evaluate([ev], None)
        assert not result.skipped
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(amber) == 1
        assert "fragile" in amber[0].summary
        assert amber[0].pattern_tag == "jdep-instability-high"

    def test_no_amber_when_high_instability_high_abstractness(self) -> None:
        ev = _make_packages_evidence(
            packages=[
                {"name": "com.example.api", "Ca": 1, "Ce": 10, "A": 0.8, "I": 0.91, "D": 0.29},
            ]
        )
        rule = JDepInstabilityRule()
        result = rule.evaluate([ev], None)
        assert not result.skipped
        assert all(f.rag == "green" for f in result.findings)

    def test_boundary_values_not_flagged(self) -> None:
        ev = _make_packages_evidence(
            packages=[
                {
                    "name": "com.example.boundary",
                    "Ca": 1,
                    "Ce": 4,
                    "A": 0.2,
                    "I": 0.8,
                    "D": 0.0,
                },
            ]
        )
        rule = JDepInstabilityRule()
        result = rule.evaluate([ev], None)
        assert all(f.rag == "green" for f in result.findings)


# ---------------------------------------------------------------------------
# JDEP-DISTANCE
# ---------------------------------------------------------------------------


class TestJDepDistanceRule:
    def test_skip_when_no_evidence(self) -> None:
        rule = JDepDistanceRule()
        result = rule.evaluate([], None)
        assert result.skipped is True

    def test_skip_when_jdepend_unavailable(self) -> None:
        rule = JDepDistanceRule()
        result = rule.evaluate([_make_skip_evidence()], None)
        assert result.skipped is True

    def test_green_when_close_to_main_sequence(self) -> None:
        ev = _make_packages_evidence(
            packages=[
                {"name": "com.example.core", "Ca": 3, "Ce": 5, "A": 0.4, "I": 0.6, "D": 0.0},
            ]
        )
        rule = JDepDistanceRule()
        result = rule.evaluate([ev], None)
        assert not result.skipped
        assert all(f.rag == "green" for f in result.findings)

    def test_amber_when_far_from_main_sequence(self) -> None:
        ev = _make_packages_evidence(
            packages=[
                {
                    "name": "com.example.painful",
                    "Ca": 10,
                    "Ce": 0,
                    "A": 0.0,
                    "I": 0.0,
                    "D": 1.0,
                },
            ]
        )
        rule = JDepDistanceRule()
        result = rule.evaluate([ev], None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(amber) == 1
        assert "painful" in amber[0].summary
        assert "zone of pain" in amber[0].summary
        assert amber[0].pattern_tag == "jdep-distance-high"

    def test_zone_of_uselessness(self) -> None:
        _make_packages_evidence(
            packages=[
                {
                    "name": "com.example.abstract",
                    "Ca": 0,
                    "Ce": 0,
                    "A": 1.0,
                    "I": 0.0,
                    "D": 0.0,
                },
            ]
        )
        # D=0.0 when A=1.0, I=0.0 (on the main sequence). Let's use a different case.
        ev2 = _make_packages_evidence(
            packages=[
                {
                    "name": "com.example.useless",
                    "Ca": 0,
                    "Ce": 1,
                    "A": 0.9,
                    "I": 0.1,
                    "D": 0.8,
                },
            ]
        )
        rule = JDepDistanceRule()
        result = rule.evaluate([ev2], None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(amber) == 1
        assert "zone of uselessness" in amber[0].summary

    def test_boundary_value_not_flagged(self) -> None:
        ev = _make_packages_evidence(
            packages=[
                {"name": "com.example.edge", "Ca": 3, "Ce": 3, "A": 0.3, "I": 0.5, "D": 0.5},
            ]
        )
        rule = JDepDistanceRule()
        result = rule.evaluate([ev], None)
        assert all(f.rag == "green" for f in result.findings)

    def test_multiple_packages_mixed(self) -> None:
        ev = _make_packages_evidence(
            packages=[
                {"name": "com.good", "Ca": 3, "Ce": 5, "A": 0.4, "I": 0.6, "D": 0.0},
                {"name": "com.bad", "Ca": 10, "Ce": 0, "A": 0.0, "I": 0.0, "D": 1.0},
            ]
        )
        rule = JDepDistanceRule()
        result = rule.evaluate([ev], None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(amber) == 1
        assert "com.bad" in amber[0].summary
