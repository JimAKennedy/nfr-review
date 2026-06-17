# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for external rule plugin discovery via entry-points."""

from __future__ import annotations

import types
from importlib.metadata import EntryPoint
from typing import Any
from unittest.mock import patch

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.plugin_discovery import HYGIENE_RULES_GROUP, RULES_GROUP, discover_plugins
from nfr_review.protocols import Band
from nfr_review.registry import Registry


class _StubRule:
    """Minimal rule that satisfies the Rule protocol."""

    def __init__(self, rule_id: str) -> None:
        self.id = rule_id
        self.band: Band = 1
        self.required_collectors: list[str] = []

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        return RuleResult(
            rule_id=self.id,
            findings=[
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary="stub finding",
                    recommendation="none",
                    evidence_locator="test://stub",
                    collector_name="stub",
                    collector_version="0.0.0",
                    confidence=1.0,
                    pattern_tag="stub",
                )
            ],
        )


def _make_plugin_module(registry: Registry, rule_id: str) -> types.ModuleType:
    """Create a fake module that self-registers a rule on import."""
    mod = types.ModuleType(f"fake_plugin_{rule_id}")
    rule = _StubRule(rule_id)
    registry.register(rule_id, rule)
    return mod


class TestDiscoverPlugins:
    def test_discovers_external_rules(self) -> None:
        reg: Registry = Registry("rule")
        reg.register("builtin-001", _StubRule("builtin-001"))

        def _fake_load(ep: EntryPoint) -> types.ModuleType:
            return _make_plugin_module(reg, "EXT-001")

        ep = EntryPoint(name="my_plugin", value="my_plugin.rules", group=RULES_GROUP)

        with patch("nfr_review.plugin_discovery.entry_points", return_value=[ep]):
            with patch.object(EntryPoint, "load", _fake_load):
                loaded = discover_plugins(reg, RULES_GROUP)

        assert "EXT-001" in loaded
        assert "EXT-001" in reg
        assert "builtin-001" in reg

    def test_builtin_wins_on_duplicate(self) -> None:
        reg: Registry = Registry("rule")
        builtin = _StubRule("DUPE-001")
        reg.register("DUPE-001", builtin)

        def _fake_load(ep: EntryPoint) -> types.ModuleType:
            mod = types.ModuleType("fake_dupe")
            try:
                reg.register("DUPE-001", _StubRule("DUPE-001"))
            except ValueError:
                pass
            return mod

        ep = EntryPoint(name="dupe_plugin", value="dupe_plugin.rules", group=RULES_GROUP)

        with patch("nfr_review.plugin_discovery.entry_points", return_value=[ep]):
            with patch.object(EntryPoint, "load", _fake_load):
                loaded = discover_plugins(reg, RULES_GROUP)

        assert "DUPE-001" not in loaded
        assert reg.get("DUPE-001") is builtin

    def test_broken_plugin_does_not_crash(self) -> None:
        reg: Registry = Registry("rule")

        ep = EntryPoint(name="broken", value="broken.rules", group=RULES_GROUP)

        with patch("nfr_review.plugin_discovery.entry_points", return_value=[ep]):
            with patch.object(EntryPoint, "load", side_effect=ImportError("no such module")):
                loaded = discover_plugins(reg, RULES_GROUP)

        assert loaded == []
        assert len(reg) == 0

    def test_multiple_plugins(self) -> None:
        reg: Registry = Registry("rule")

        def _make_loader(rule_id: str):
            def _load(ep: EntryPoint) -> types.ModuleType:
                return _make_plugin_module(reg, rule_id)

            return _load

        ep1 = EntryPoint(name="plugin_a", value="plugin_a.rules", group=RULES_GROUP)
        ep2 = EntryPoint(name="plugin_b", value="plugin_b.rules", group=RULES_GROUP)

        with patch("nfr_review.plugin_discovery.entry_points", return_value=[ep1, ep2]):
            calls = iter(["EXT-A01", "EXT-B01"])

            def _dispatch_load(self: EntryPoint) -> types.ModuleType:
                return _make_plugin_module(reg, next(calls))

            with patch.object(EntryPoint, "load", _dispatch_load):
                loaded = discover_plugins(reg, RULES_GROUP)

        assert "EXT-A01" in loaded
        assert "EXT-B01" in loaded
        assert len(reg) == 2

    def test_hygiene_group_constant(self) -> None:
        assert HYGIENE_RULES_GROUP == "nfr_review.hygiene_rules"

    def test_no_plugins_returns_empty(self) -> None:
        reg: Registry = Registry("rule")
        with patch("nfr_review.plugin_discovery.entry_points", return_value=[]):
            loaded = discover_plugins(reg, RULES_GROUP)
        assert loaded == []

    def test_external_rule_produces_findings(self) -> None:
        """End-to-end: discovered rule can be retrieved and evaluated."""
        reg: Registry = Registry("rule")

        def _fake_load(ep: EntryPoint) -> types.ModuleType:
            return _make_plugin_module(reg, "EXT-EVAL-001")

        ep = EntryPoint(name="eval_plugin", value="eval_plugin.rules", group=RULES_GROUP)

        with patch("nfr_review.plugin_discovery.entry_points", return_value=[ep]):
            with patch.object(EntryPoint, "load", _fake_load):
                discover_plugins(reg, RULES_GROUP)

        rule = reg.get("EXT-EVAL-001")
        result = rule.evaluate([], None)
        assert len(result.findings) == 1
        assert result.findings[0].rule_id == "EXT-EVAL-001"
