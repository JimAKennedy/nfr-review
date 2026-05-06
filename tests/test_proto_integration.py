"""Proto integration tests — collector + rules pipeline on real fixture files."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.collectors.proto import ProtoCollector
from nfr_review.models import Evidence, Finding
from nfr_review.rules.proto_field_numbering import ProtoFieldNumberingRule
from nfr_review.rules.proto_method_comments import ProtoMethodCommentsRule
from nfr_review.rules.proto_service_versioning import ProtoServiceVersioningRule

FIXTURES = Path(__file__).parent / "fixtures" / "proto-sample-repo"

R007_FIELDS = {
    "rule_id",
    "rag",
    "severity",
    "summary",
    "recommendation",
    "evidence_locator",
    "collector_name",
    "collector_version",
    "confidence",
    "pattern_tag",
}

PROTO_RULE_IDS = {
    "proto-field-numbering",
    "proto-service-versioning",
    "proto-method-comments",
}


@pytest.fixture()
def evidence() -> list[Evidence]:
    collector = ProtoCollector()
    return collector.collect(FIXTURES, config=None)


def _evidence_for(evidence: list[Evidence], substr: str) -> list[Evidence]:
    return [e for e in evidence if substr in e.payload["file_path"]]


class TestCollectorProducesEvidence:
    def test_four_evidence_objects(self, evidence: list[Evidence]) -> None:
        assert len(evidence) == 4

    def test_all_are_proto_analysis(self, evidence: list[Evidence]) -> None:
        for ev in evidence:
            assert ev.kind == "proto-analysis"
            assert ev.collector_name == "proto"

    def test_locators_match_fixture_names(self, evidence: list[Evidence]) -> None:
        locators = {e.locator for e in evidence}
        assert locators == {
            "good.proto",
            "bad_gaps.proto",
            "bad_service.proto",
            "with_reserved.proto",
        }


class TestFieldNumberingOnFixtures:
    @pytest.fixture()
    def rule(self) -> ProtoFieldNumberingRule:
        return ProtoFieldNumberingRule()

    def test_bad_gaps_triggers_amber(
        self, rule: ProtoFieldNumberingRule, evidence: list[Evidence]
    ) -> None:
        result = rule.evaluate(evidence, None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(amber) >= 1
        assert any("Account" in f.summary for f in amber)
        assert any("Event" in f.summary for f in amber)

    def test_good_proto_no_amber(
        self, rule: ProtoFieldNumberingRule, evidence: list[Evidence]
    ) -> None:
        good_ev = _evidence_for(evidence, "good.proto")
        result = rule.evaluate(good_ev, None)
        assert all(f.rag == "green" for f in result.findings)

    def test_with_reserved_no_amber(
        self, rule: ProtoFieldNumberingRule, evidence: list[Evidence]
    ) -> None:
        reserved_ev = _evidence_for(evidence, "with_reserved.proto")
        result = rule.evaluate(reserved_ev, None)
        assert all(f.rag == "green" for f in result.findings)


class TestServiceVersioningOnFixtures:
    @pytest.fixture()
    def rule(self) -> ProtoServiceVersioningRule:
        return ProtoServiceVersioningRule()

    def test_bad_service_triggers_amber(
        self, rule: ProtoServiceVersioningRule, evidence: list[Evidence]
    ) -> None:
        result = rule.evaluate(evidence, None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(amber) >= 1
        assert any("OrderService" in f.summary for f in amber)

    def test_good_proto_versioned_green(
        self, rule: ProtoServiceVersioningRule, evidence: list[Evidence]
    ) -> None:
        good_ev = _evidence_for(evidence, "good.proto")
        result = rule.evaluate(good_ev, None)
        assert all(f.rag == "green" for f in result.findings)


class TestMethodCommentsOnFixtures:
    @pytest.fixture()
    def rule(self) -> ProtoMethodCommentsRule:
        return ProtoMethodCommentsRule()

    def test_bad_service_triggers_amber(
        self, rule: ProtoMethodCommentsRule, evidence: list[Evidence]
    ) -> None:
        result = rule.evaluate(evidence, None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(amber) >= 1
        assert any("OrderService" in f.summary for f in amber)

    def test_good_proto_commented_green(
        self, rule: ProtoMethodCommentsRule, evidence: list[Evidence]
    ) -> None:
        good_ev = _evidence_for(evidence, "good.proto")
        result = rule.evaluate(good_ev, None)
        assert all(f.rag == "green" for f in result.findings)


class TestFindingR007Completeness:
    """Verify all findings have the 10 R007 fields populated."""

    def test_all_findings_have_r007_fields(self, evidence: list[Evidence]) -> None:
        rules = [
            ProtoFieldNumberingRule(),
            ProtoServiceVersioningRule(),
            ProtoMethodCommentsRule(),
        ]
        all_findings: list[Finding] = []
        for rule in rules:
            result = rule.evaluate(evidence, None)
            all_findings.extend(result.findings)

        assert len(all_findings) >= 3

        for finding in all_findings:
            data = finding.model_dump()
            for field in R007_FIELDS:
                assert field in data, f"Missing R007 field: {field}"
                assert data[field] is not None, f"R007 field {field} is None"
                if isinstance(data[field], str):
                    assert data[field] != "", f"R007 field {field} is empty"

    def test_confidence_in_range(self, evidence: list[Evidence]) -> None:
        rules = [
            ProtoFieldNumberingRule(),
            ProtoServiceVersioningRule(),
            ProtoMethodCommentsRule(),
        ]
        for rule in rules:
            result = rule.evaluate(evidence, None)
            for finding in result.findings:
                assert 0.0 <= finding.confidence <= 1.0

    def test_rule_ids_match_known_set(self, evidence: list[Evidence]) -> None:
        rules = [
            ProtoFieldNumberingRule(),
            ProtoServiceVersioningRule(),
            ProtoMethodCommentsRule(),
        ]
        seen_ids: set[str] = set()
        for rule in rules:
            result = rule.evaluate(evidence, None)
            for finding in result.findings:
                seen_ids.add(finding.rule_id)

        assert seen_ids == PROTO_RULE_IDS
