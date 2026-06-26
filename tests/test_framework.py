# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for the typed rule framework (Hit, make_finding, FieldRule[P])."""

from __future__ import annotations

from collections.abc import Iterable

import pytest
from pydantic import ConfigDict, ValidationError

from nfr_review.models import BasePayload, Evidence, Finding
from nfr_review.rules.framework import FieldRule, Hit, make_finding


# ---------------------------------------------------------------------------
# Minimal test payload
# ---------------------------------------------------------------------------
class SamplePayload(BasePayload):
    file_path: str = ""
    score: int = 0
    tag: str = ""


def _make_evidence(
    payload: dict | BasePayload | None = None,
    collector_name: str = "test-collector",
    kind: str = "test-kind",
) -> Evidence:
    return Evidence(
        collector_name=collector_name,
        collector_version="1.0.0",
        locator="test",
        kind=kind,
        payload=payload
        if payload is not None
        else {"file_path": "a.py", "score": 42, "tag": "x"},
    )


# ---------------------------------------------------------------------------
# Hit tests
# ---------------------------------------------------------------------------
class TestHit:
    def test_construction(self) -> None:
        h = Hit(rag="amber", summary="s", recommendation="r", locator="f.py:1")
        assert h.rag == "amber"
        assert h.summary == "s"
        assert h.severity is None
        assert h.confidence is None
        assert h.pattern_tag is None
        assert h.content_hash == ""

    def test_frozen(self) -> None:
        h = Hit(rag="red", summary="s", recommendation="r", locator="f.py:1")
        with pytest.raises(AttributeError):
            h.rag = "green"  # type: ignore[misc]

    def test_explicit_fields(self) -> None:
        h = Hit(
            rag="red",
            summary="s",
            recommendation="r",
            locator="f.py:1",
            severity="critical",
            confidence=0.95,
            pattern_tag="custom",
            content_hash="abc123",
        )
        assert h.severity == "critical"
        assert h.confidence == 0.95
        assert h.pattern_tag == "custom"
        assert h.content_hash == "abc123"


# ---------------------------------------------------------------------------
# make_finding tests
# ---------------------------------------------------------------------------
class TestMakeFinding:
    def test_severity_from_rag(self) -> None:
        ev = _make_evidence()
        for rag, expected in [("red", "high"), ("amber", "medium"), ("green", "info")]:
            hit = Hit(rag=rag, summary="s", recommendation="r", locator="f:1")
            f = make_finding(rule_id="r1", hit=hit, ev=ev, pattern_tag="p")
            assert f.severity == expected

    def test_explicit_severity_overrides_rag(self) -> None:
        ev = _make_evidence()
        hit = Hit(
            rag="red", summary="s", recommendation="r", locator="f:1", severity="critical"
        )
        f = make_finding(rule_id="r1", hit=hit, ev=ev, pattern_tag="p")
        assert f.severity == "critical"

    def test_default_confidence(self) -> None:
        ev = _make_evidence()
        hit = Hit(rag="green", summary="s", recommendation="r", locator="f:1")
        f = make_finding(
            rule_id="r1", hit=hit, ev=ev, pattern_tag="p", default_confidence=0.85
        )
        assert f.confidence == 0.85

    def test_explicit_confidence_overrides_default(self) -> None:
        ev = _make_evidence()
        hit = Hit(rag="green", summary="s", recommendation="r", locator="f:1", confidence=0.5)
        f = make_finding(
            rule_id="r1", hit=hit, ev=ev, pattern_tag="p", default_confidence=0.85
        )
        assert f.confidence == 0.5

    def test_zero_confidence_is_explicit(self) -> None:
        ev = _make_evidence()
        hit = Hit(rag="green", summary="s", recommendation="r", locator="f:1", confidence=0.0)
        f = make_finding(rule_id="r1", hit=hit, ev=ev, pattern_tag="p", default_confidence=0.9)
        assert f.confidence == 0.0

    def test_pattern_tag_from_hit(self) -> None:
        ev = _make_evidence()
        hit = Hit(
            rag="green", summary="s", recommendation="r", locator="f:1", pattern_tag="custom"
        )
        f = make_finding(rule_id="r1", hit=hit, ev=ev, pattern_tag="default")
        assert f.pattern_tag == "custom"

    def test_pattern_tag_falls_back_to_param(self) -> None:
        ev = _make_evidence()
        hit = Hit(rag="green", summary="s", recommendation="r", locator="f:1")
        f = make_finding(rule_id="r1", hit=hit, ev=ev, pattern_tag="default")
        assert f.pattern_tag == "default"

    def test_collector_fields_from_evidence(self) -> None:
        ev = _make_evidence(collector_name="my-collector")
        hit = Hit(rag="green", summary="s", recommendation="r", locator="f:1")
        f = make_finding(rule_id="r1", hit=hit, ev=ev, pattern_tag="p")
        assert f.collector_name == "my-collector"
        assert f.collector_version == "1.0.0"

    def test_content_hash_propagated(self) -> None:
        ev = _make_evidence()
        hit = Hit(
            rag="green", summary="s", recommendation="r", locator="f:1", content_hash="h1"
        )
        f = make_finding(rule_id="r1", hit=hit, ev=ev, pattern_tag="p")
        assert f.content_hash == "h1"

    def test_returns_finding_type(self) -> None:
        ev = _make_evidence()
        hit = Hit(rag="green", summary="s", recommendation="r", locator="f:1")
        f = make_finding(rule_id="r1", hit=hit, ev=ev, pattern_tag="p")
        assert isinstance(f, Finding)


# ---------------------------------------------------------------------------
# FieldRule tests — concrete subclass for testing
# ---------------------------------------------------------------------------
class ScoreCheckRule(FieldRule[SamplePayload]):
    # id set after class creation to avoid auto-registration in global registry
    collector_name = "test-collector"
    evidence_kind = "test-kind"
    payload_type = SamplePayload
    pattern_tag = "score-check"
    all_clear_summary = "All scores are acceptable."
    all_clear_recommendation = "No remediation needed."

    def check(self, payload: SamplePayload, ev: Evidence) -> Iterable[Hit]:
        if payload.score > 100:
            yield Hit(
                rag="red",
                summary=f"Score {payload.score} exceeds threshold",
                recommendation="Reduce score below 100",
                locator=f"{payload.file_path}:{payload.score}",
            )
        elif payload.score > 50:
            yield Hit(
                rag="amber",
                summary=f"Score {payload.score} is elevated",
                recommendation="Consider reducing score",
                locator=f"{payload.file_path}:{payload.score}",
            )


ScoreCheckRule.id = "test-score-check"


class TestFieldRuleInitSubclass:
    def test_required_collectors_auto_populated(self) -> None:
        assert ScoreCheckRule.required_collectors == ["test-collector"]

    def test_band_defaults_to_1(self) -> None:
        assert ScoreCheckRule.band == 1

    def test_explicit_required_collectors_not_overwritten(self) -> None:
        class CustomCollectors(FieldRule[SamplePayload]):
            collector_name = "a"
            evidence_kind = "b"
            payload_type = SamplePayload
            pattern_tag = "p"
            required_collectors = ["a", "b"]

            def check(self, payload: SamplePayload, ev: Evidence) -> Iterable[Hit]:
                return []

        CustomCollectors.id = "custom"
        assert CustomCollectors.required_collectors == ["a", "b"]


class TestFieldRuleEvaluate:
    def test_skip_when_no_matching_evidence(self) -> None:
        rule = ScoreCheckRule()
        result = rule.evaluate(
            [_make_evidence(collector_name="other-collector")],
            context=None,
        )
        assert result.skipped is True
        assert "no test-kind evidence" in result.skip_reason

    def test_skip_when_evidence_list_empty(self) -> None:
        rule = ScoreCheckRule()
        result = rule.evaluate([], context=None)
        assert result.skipped is True

    def test_skip_when_kind_mismatch(self) -> None:
        rule = ScoreCheckRule()
        result = rule.evaluate(
            [_make_evidence(kind="wrong-kind")],
            context=None,
        )
        assert result.skipped is True

    def test_green_all_clear_when_check_yields_nothing(self) -> None:
        rule = ScoreCheckRule()
        ev = _make_evidence(payload={"file_path": "ok.py", "score": 10, "tag": "t"})
        result = rule.evaluate([ev], context=None)
        assert not result.skipped
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "green"
        assert f.severity == "info"
        assert f.summary == "All scores are acceptable."
        assert f.recommendation == "No remediation needed."
        assert f.evidence_locator == "project-wide"

    def test_amber_finding_produced(self) -> None:
        rule = ScoreCheckRule()
        ev = _make_evidence(payload={"file_path": "warn.py", "score": 75, "tag": "t"})
        result = rule.evaluate([ev], context=None)
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "amber"
        assert f.severity == "medium"
        assert "75" in f.summary
        assert f.pattern_tag == "score-check"
        assert f.rule_id == "test-score-check"

    def test_red_finding_produced(self) -> None:
        rule = ScoreCheckRule()
        ev = _make_evidence(payload={"file_path": "bad.py", "score": 200, "tag": "t"})
        result = rule.evaluate([ev], context=None)
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "red"
        assert f.severity == "high"

    def test_multiple_evidence_multiple_findings(self) -> None:
        rule = ScoreCheckRule()
        ev1 = _make_evidence(payload={"file_path": "a.py", "score": 200, "tag": "t"})
        ev2 = _make_evidence(payload={"file_path": "b.py", "score": 75, "tag": "t"})
        result = rule.evaluate([ev1, ev2], context=None)
        assert len(result.findings) == 2
        rags = {f.rag for f in result.findings}
        assert rags == {"red", "amber"}

    def test_mixed_evidence_filters_correctly(self) -> None:
        rule = ScoreCheckRule()
        matching = _make_evidence(payload={"file_path": "a.py", "score": 200, "tag": "t"})
        non_matching = _make_evidence(collector_name="other", payload={"x": 1})
        result = rule.evaluate([non_matching, matching], context=None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "red"


class TestFieldRuleCoerce:
    def test_dict_to_typed_payload(self) -> None:
        rule = ScoreCheckRule()
        raw = {"file_path": "test.py", "score": 42, "tag": "x"}
        result = rule._coerce(raw)
        assert isinstance(result, SamplePayload)
        assert result.file_path == "test.py"
        assert result.score == 42

    def test_typed_payload_fast_path(self) -> None:
        rule = ScoreCheckRule()
        typed = SamplePayload(file_path="test.py", score=42, tag="x")
        result = rule._coerce(typed)
        assert result is typed  # same object, no validation

    def test_different_basepayload_round_trips(self) -> None:
        class OtherPayload(BasePayload):
            file_path: str = ""
            score: int = 0
            tag: str = ""
            extra_field: str = "ignored"

            model_config = ConfigDict(extra="ignore")

        rule = ScoreCheckRule()
        other = OtherPayload(file_path="o.py", score=99, tag="y", extra_field="z")
        result = rule._coerce(other)
        assert isinstance(result, SamplePayload)
        assert result.file_path == "o.py"
        assert result.score == 99

    def test_validation_failure_raises(self) -> None:
        rule = ScoreCheckRule()
        with pytest.raises(ValidationError):
            rule._coerce({"file_path": "test.py", "score": "not_an_int", "tag": "x"})

    def test_evaluate_with_dict_payload_end_to_end(self) -> None:
        rule = ScoreCheckRule()
        ev = _make_evidence(payload={"file_path": "a.py", "score": 200, "tag": "t"})
        result = rule.evaluate([ev], context=None)
        assert result.findings[0].rag == "red"

    def test_evaluate_with_typed_payload_end_to_end(self) -> None:
        rule = ScoreCheckRule()
        typed = SamplePayload(file_path="a.py", score=200, tag="t")
        ev = Evidence(
            collector_name="test-collector",
            collector_version="1.0.0",
            locator="test",
            kind="test-kind",
            payload=typed,
        )
        result = rule.evaluate([ev], context=None)
        assert result.findings[0].rag == "red"


class TestFieldRuleDefaultConfidence:
    def test_default_confidence_used(self) -> None:
        class HighConfRule(FieldRule[SamplePayload]):
            collector_name = "test-collector"
            evidence_kind = "test-kind"
            payload_type = SamplePayload
            pattern_tag = "p"
            default_confidence = 0.95

            def check(self, payload: SamplePayload, ev: Evidence) -> Iterable[Hit]:
                yield Hit(rag="amber", summary="s", recommendation="r", locator="f:1")

        HighConfRule.id = "high-conf"
        rule = HighConfRule()
        ev = _make_evidence()
        result = rule.evaluate([ev], context=None)
        assert result.findings[0].confidence == 0.95

    def test_hit_confidence_overrides_default(self) -> None:
        class OverrideRule(FieldRule[SamplePayload]):
            collector_name = "test-collector"
            evidence_kind = "test-kind"
            payload_type = SamplePayload
            pattern_tag = "p"
            default_confidence = 0.95

            def check(self, payload: SamplePayload, ev: Evidence) -> Iterable[Hit]:
                yield Hit(
                    rag="amber", summary="s", recommendation="r", locator="f:1", confidence=0.5
                )

        OverrideRule.id = "override"
        rule = OverrideRule()
        ev = _make_evidence()
        result = rule.evaluate([ev], context=None)
        assert result.findings[0].confidence == 0.5
