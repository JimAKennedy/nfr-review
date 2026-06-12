# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for shared AST rule infrastructure (rules/ast_common.py)."""

from __future__ import annotations

import pytest

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.rules.ast_common import GenericASTRule, LanguageRuleConfig

# ---------------------------------------------------------------------------
# LanguageRuleConfig dataclass
# ---------------------------------------------------------------------------


def test_language_rule_config_construction() -> None:
    cfg = LanguageRuleConfig(
        language="python",
        collector_name="python-ast",
        evidence_kind="python-ast-file",
        tech_key="python",
    )
    assert cfg.language == "python"
    assert cfg.collector_name == "python-ast"
    assert cfg.evidence_kind == "python-ast-file"
    assert cfg.tech_key == "python"


def test_language_rule_config_frozen() -> None:
    cfg = LanguageRuleConfig(
        language="go",
        collector_name="go-ast",
        evidence_kind="go-ast-file",
        tech_key="go",
    )
    with pytest.raises(AttributeError):
        cfg.language = "java"  # type: ignore[misc]


def test_language_rule_config_slots() -> None:
    cfg = LanguageRuleConfig(
        language="java",
        collector_name="java-ast",
        evidence_kind="java-ast-file",
        tech_key="java",
    )
    assert hasattr(cfg, "__slots__")


# ---------------------------------------------------------------------------
# Concrete test subclass of GenericASTRule
# ---------------------------------------------------------------------------


class _TestASTRule(GenericASTRule):
    """Minimal concrete rule for testing the base class logic."""

    id = "TEST-001"
    pattern_tag = "test-pattern"
    language_configs = [
        LanguageRuleConfig(
            language="python",
            collector_name="python-ast",
            evidence_kind="python-ast-file",
            tech_key="python",
        ),
    ]

    def __init__(self, findings_to_return: list[Finding] | None = None) -> None:
        self._findings = findings_to_return or []

    def check_match(self, evidence: Evidence, config: LanguageRuleConfig) -> list[Finding]:
        return list(self._findings)


def _make_evidence(
    collector_name: str = "python-ast",
    kind: str = "python-ast-file",
    locator: str = "src/app.py",
    version: str = "1.0.0",
) -> Evidence:
    return Evidence(
        collector_name=collector_name,
        collector_version=version,
        locator=locator,
        kind=kind,
        payload={"file_path": locator},
    )


def _make_finding(
    rule_id: str = "TEST-001",
    rag: str = "amber",
    severity: str = "medium",
    summary: str = "Found an issue",
    pattern_tag: str = "test-pattern",
    locator: str = "src/app.py:10",
) -> Finding:
    return Finding(
        rule_id=rule_id,
        rag=rag,
        severity=severity,
        summary=summary,
        recommendation="Fix it",
        evidence_locator=locator,
        collector_name="python-ast",
        collector_version="1.0.0",
        confidence=0.9,
        pattern_tag=pattern_tag,
    )


# ---------------------------------------------------------------------------
# GenericASTRule.evaluate() — no matching evidence → skipped
# ---------------------------------------------------------------------------


def test_evaluate_no_matching_evidence_skipped() -> None:
    rule = _TestASTRule()
    # Evidence from a completely different collector
    evidence = [_make_evidence(collector_name="other-collector", kind="other-kind")]
    result = rule.evaluate(evidence, context=None)

    assert isinstance(result, RuleResult)
    assert result.rule_id == "TEST-001"
    assert result.skipped is True
    assert "no matching AST evidence" in (result.skip_reason or "")


def test_evaluate_empty_evidence_skipped() -> None:
    rule = _TestASTRule()
    result = rule.evaluate([], context=None)

    assert result.skipped is True
    assert result.findings == []


# ---------------------------------------------------------------------------
# GenericASTRule.evaluate() — matching evidence with findings
# ---------------------------------------------------------------------------


def test_evaluate_matching_evidence_with_findings() -> None:
    finding = _make_finding()
    rule = _TestASTRule(findings_to_return=[finding])
    evidence = [_make_evidence()]
    result = rule.evaluate(evidence, context=None)

    assert result.skipped is False
    assert len(result.findings) == 1
    assert result.findings[0].summary == "Found an issue"
    assert result.findings[0].rag == "amber"


def test_evaluate_multiple_evidence_items_accumulate_findings() -> None:
    finding = _make_finding()
    rule = _TestASTRule(findings_to_return=[finding])
    evidence = [
        _make_evidence(locator="src/a.py"),
        _make_evidence(locator="src/b.py"),
    ]
    result = rule.evaluate(evidence, context=None)

    assert result.skipped is False
    # Each evidence item produces the same finding, so 2 total
    assert len(result.findings) == 2


# ---------------------------------------------------------------------------
# GenericASTRule.evaluate() — matching evidence, no findings → green
# ---------------------------------------------------------------------------


def test_evaluate_matching_evidence_no_findings_green() -> None:
    rule = _TestASTRule(findings_to_return=[])
    evidence = [_make_evidence()]
    result = rule.evaluate(evidence, context=None)

    assert result.skipped is False
    assert len(result.findings) == 1
    green = result.findings[0]
    assert green.rag == "green"
    assert green.severity == "info"
    assert "No test-pattern issues" in green.summary
    assert green.evidence_locator == "project-wide"
    assert green.collector_name == "python-ast"
    assert green.confidence == 0.85


# ---------------------------------------------------------------------------
# Multiple language configs — mixed match / no-match
# ---------------------------------------------------------------------------


_MULTI_LANG_CONFIGS = [
    LanguageRuleConfig(
        language="python",
        collector_name="python-ast",
        evidence_kind="python-ast-file",
        tech_key="python",
    ),
    LanguageRuleConfig(
        language="java",
        collector_name="java-ast",
        evidence_kind="java-ast-file",
        tech_key="java",
    ),
]


class _MultiLangRule(GenericASTRule):
    id = "MULTI-001"
    pattern_tag = "multi-pattern"
    language_configs = _MULTI_LANG_CONFIGS

    def __init__(self) -> None:
        self._call_log: list[str] = []

    def check_match(self, evidence: Evidence, config: LanguageRuleConfig) -> list[Finding]:
        self._call_log.append(config.language)
        return [
            _make_finding(
                rule_id="MULTI-001",
                pattern_tag="multi-pattern",
                summary=f"Issue in {config.language}",
            )
        ]


def test_evaluate_multi_lang_only_matching_languages_called() -> None:
    rule = _MultiLangRule()
    # Only Python evidence — Java config should not trigger check_match
    evidence = [_make_evidence(collector_name="python-ast", kind="python-ast-file")]
    result = rule.evaluate(evidence, context=None)

    assert result.skipped is False
    assert len(result.findings) == 1
    assert rule._call_log == ["python"]


def test_evaluate_multi_lang_both_languages_present() -> None:
    rule = _MultiLangRule()
    evidence = [
        _make_evidence(collector_name="python-ast", kind="python-ast-file"),
        _make_evidence(collector_name="java-ast", kind="java-ast-file", locator="Main.java"),
    ]
    result = rule.evaluate(evidence, context=None)

    assert result.skipped is False
    assert len(result.findings) == 2
    assert set(rule._call_log) == {"python", "java"}


def test_evaluate_multi_lang_no_matching_evidence() -> None:
    rule = _MultiLangRule()
    evidence = [_make_evidence(collector_name="go-ast", kind="go-ast-file")]
    result = rule.evaluate(evidence, context=None)

    assert result.skipped is True
    assert result.findings == []


# ---------------------------------------------------------------------------
# Green finding uses first evidence's collector_version
# ---------------------------------------------------------------------------


def test_green_finding_uses_evidence_version() -> None:
    rule = _TestASTRule(findings_to_return=[])
    evidence = [_make_evidence(version="2.3.4")]
    result = rule.evaluate(evidence, context=None)

    green = result.findings[0]
    assert green.collector_version == "2.3.4"
