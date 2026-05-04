from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nfr_review.models import Evidence, RuleResult
from nfr_review.registry import (
    Registry,
    collector_registry,
    list_collectors,
    list_rules,
    rule_registry,
)


class _FakeCollector:
    name = "fake"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        return []


class _FakeRule:
    id = "fake-rule"
    band = 1
    required_collectors: list[str] = ["fake"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        return RuleResult(rule_id=self.id)


@pytest.fixture(autouse=True)
def _reset_singletons() -> None:
    rule_registry.clear()
    collector_registry.clear()
    yield
    rule_registry.clear()
    collector_registry.clear()


def test_register_and_get() -> None:
    reg: Registry[_FakeCollector] = Registry("collector")
    c = _FakeCollector()
    reg.register("fake", c)
    assert reg.get("fake") is c


def test_register_rejects_duplicate_id() -> None:
    reg: Registry[_FakeCollector] = Registry("collector")
    reg.register("fake", _FakeCollector())
    with pytest.raises(ValueError) as exc_info:
        reg.register("fake", _FakeCollector())
    assert "fake" in str(exc_info.value)


def test_get_missing_raises_keyerror_with_id() -> None:
    reg: Registry[_FakeCollector] = Registry("collector")
    with pytest.raises(KeyError) as exc_info:
        reg.get("does-not-exist")
    assert "does-not-exist" in str(exc_info.value)


def test_all_returns_registered_items() -> None:
    reg: Registry[_FakeCollector] = Registry("collector")
    a = _FakeCollector()
    b = _FakeCollector()
    reg.register("a", a)
    reg.register("b", b)
    assert reg.all() == [a, b]
    assert reg.list() == [a, b]


def test_ids_returns_keys_in_insertion_order() -> None:
    reg: Registry[_FakeCollector] = Registry("collector")
    reg.register("first", _FakeCollector())
    reg.register("second", _FakeCollector())
    assert reg.ids() == ["first", "second"]


def test_registry_contains_and_len() -> None:
    reg: Registry[_FakeCollector] = Registry("collector")
    assert len(reg) == 0
    assert "x" not in reg
    reg.register("x", _FakeCollector())
    assert "x" in reg
    assert len(reg) == 1


def test_singletons_are_distinct() -> None:
    assert rule_registry is not collector_registry


def test_rule_registry_singleton_register_and_lookup() -> None:
    rule = _FakeRule()
    rule_registry.register(rule.id, rule)
    assert rule_registry.get("fake-rule") is rule
    assert list_rules() == [rule]


def test_collector_registry_singleton_register_and_lookup() -> None:
    collector = _FakeCollector()
    collector_registry.register(collector.name, collector)
    assert collector_registry.get("fake") is collector
    assert list_collectors() == [collector]


def test_singleton_duplicate_register_raises() -> None:
    rule_registry.register("dup", _FakeRule())
    with pytest.raises(ValueError):
        rule_registry.register("dup", _FakeRule())


def test_registry_kind_appears_in_error_messages() -> None:
    rule_reg: Registry[_FakeRule] = Registry("rule")
    rule_reg.register("r", _FakeRule())
    with pytest.raises(ValueError) as dup:
        rule_reg.register("r", _FakeRule())
    assert "rule" in str(dup.value)

    with pytest.raises(KeyError) as missing:
        rule_reg.get("missing")
    assert "rule" in str(missing.value)
