"""Tests for proto NFR rules: field-numbering, service-versioning, method-comments."""

from __future__ import annotations

import pytest

from nfr_review.models import Evidence
from nfr_review.registry import rule_registry
from nfr_review.rules.proto_field_numbering import ProtoFieldNumberingRule
from nfr_review.rules.proto_method_comments import ProtoMethodCommentsRule
from nfr_review.rules.proto_service_versioning import ProtoServiceVersioningRule


def _make_evidence(
    *,
    messages: list[dict] | None = None,
    services: list[dict] | None = None,
    package: str | None = None,
) -> list[Evidence]:
    return [
        Evidence(
            collector_name="proto",
            collector_version="0.1.0",
            locator="test.proto",
            kind="proto-analysis",
            payload={
                "file_path": "test.proto",
                "syntax": "proto3",
                "package": package,
                "imports": [],
                "messages": messages or [],
                "services": services or [],
                "enums": [],
            },
        )
    ]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_field_numbering_registered(self) -> None:
        assert "proto-field-numbering" in rule_registry

    def test_service_versioning_registered(self) -> None:
        assert "proto-service-versioning" in rule_registry

    def test_method_comments_registered(self) -> None:
        assert "proto-method-comments" in rule_registry


# ---------------------------------------------------------------------------
# ProtoFieldNumberingRule
# ---------------------------------------------------------------------------


class TestFieldNumbering:
    @pytest.fixture()
    def rule(self) -> ProtoFieldNumberingRule:
        return ProtoFieldNumberingRule()

    def test_skip_no_evidence(self, rule: ProtoFieldNumberingRule) -> None:
        result = rule.evaluate([], None)
        assert result.skipped is True
        assert result.rule_id == "proto-field-numbering"

    def test_skip_wrong_collector(self, rule: ProtoFieldNumberingRule) -> None:
        ev = [
            Evidence(
                collector_name="other",
                collector_version="1.0",
                locator="x",
                kind="other",
                payload={},
            )
        ]
        result = rule.evaluate(ev, None)
        assert result.skipped is True

    def test_consecutive_numbers_green(self, rule: ProtoFieldNumberingRule) -> None:
        evidence = _make_evidence(
            messages=[
                {
                    "name": "Order",
                    "line": 5,
                    "has_comment": False,
                    "fields": [
                        {"name": "id", "number": 1, "type": "int64", "label": "", "line": 6},
                        {
                            "name": "name",
                            "number": 2,
                            "type": "string",
                            "label": "",
                            "line": 7,
                        },
                        {
                            "name": "amount",
                            "number": 3,
                            "type": "int32",
                            "label": "",
                            "line": 8,
                        },
                    ],
                    "reserved_numbers": [],
                    "reserved_ranges": [],
                }
            ]
        )
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_gap_without_reserved_amber(self, rule: ProtoFieldNumberingRule) -> None:
        evidence = _make_evidence(
            messages=[
                {
                    "name": "Product",
                    "line": 10,
                    "has_comment": False,
                    "fields": [
                        {"name": "id", "number": 1, "type": "int64", "label": "", "line": 11},
                        {
                            "name": "name",
                            "number": 3,
                            "type": "string",
                            "label": "",
                            "line": 12,
                        },
                    ],
                    "reserved_numbers": [],
                    "reserved_ranges": [],
                }
            ]
        )
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        assert any(f.rag == "amber" for f in result.findings)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert "2" in amber[0].summary

    def test_gap_covered_by_reserved_green(self, rule: ProtoFieldNumberingRule) -> None:
        evidence = _make_evidence(
            messages=[
                {
                    "name": "Product",
                    "line": 10,
                    "has_comment": False,
                    "fields": [
                        {"name": "id", "number": 1, "type": "int64", "label": "", "line": 11},
                        {
                            "name": "name",
                            "number": 3,
                            "type": "string",
                            "label": "",
                            "line": 12,
                        },
                    ],
                    "reserved_numbers": [2],
                    "reserved_ranges": [],
                }
            ]
        )
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        assert all(f.rag == "green" for f in result.findings)

    def test_multiple_gaps(self, rule: ProtoFieldNumberingRule) -> None:
        evidence = _make_evidence(
            messages=[
                {
                    "name": "Sparse",
                    "line": 1,
                    "has_comment": False,
                    "fields": [
                        {"name": "a", "number": 1, "type": "int32", "label": "", "line": 2},
                        {"name": "b", "number": 5, "type": "int32", "label": "", "line": 3},
                    ],
                    "reserved_numbers": [3],
                    "reserved_ranges": [],
                }
            ]
        )
        result = rule.evaluate(evidence, None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(amber) == 1
        assert "2" in amber[0].summary
        assert "4" in amber[0].summary

    def test_single_field_green(self, rule: ProtoFieldNumberingRule) -> None:
        evidence = _make_evidence(
            messages=[
                {
                    "name": "Single",
                    "line": 1,
                    "has_comment": False,
                    "fields": [
                        {
                            "name": "only",
                            "number": 1,
                            "type": "string",
                            "label": "",
                            "line": 2,
                        },
                    ],
                    "reserved_numbers": [],
                    "reserved_ranges": [],
                }
            ]
        )
        result = rule.evaluate(evidence, None)
        assert all(f.rag == "green" for f in result.findings)

    def test_empty_message_skipped(self, rule: ProtoFieldNumberingRule) -> None:
        evidence = _make_evidence(
            messages=[
                {
                    "name": "Empty",
                    "line": 1,
                    "has_comment": False,
                    "fields": [],
                    "reserved_numbers": [],
                    "reserved_ranges": [],
                }
            ]
        )
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        assert all(f.rag == "green" for f in result.findings)

    def test_finding_fields_match_r007(self, rule: ProtoFieldNumberingRule) -> None:
        evidence = _make_evidence(
            messages=[
                {
                    "name": "M",
                    "line": 1,
                    "has_comment": False,
                    "fields": [
                        {"name": "a", "number": 1, "type": "int32", "label": "", "line": 2},
                        {"name": "b", "number": 3, "type": "int32", "label": "", "line": 3},
                    ],
                    "reserved_numbers": [],
                    "reserved_ranges": [],
                }
            ]
        )
        result = rule.evaluate(evidence, None)
        finding = result.findings[0]
        assert finding.rule_id == "proto-field-numbering"
        assert finding.rag in ("red", "amber", "green", "skipped")
        assert finding.severity in ("critical", "high", "medium", "low", "info")
        assert finding.summary
        assert finding.recommendation
        assert finding.evidence_locator
        assert finding.collector_name == "proto"
        assert finding.collector_version == "0.1.0"
        assert 0.0 <= finding.confidence <= 1.0
        assert finding.pattern_tag == "proto-field-numbering"


# ---------------------------------------------------------------------------
# ProtoServiceVersioningRule
# ---------------------------------------------------------------------------


class TestServiceVersioning:
    @pytest.fixture()
    def rule(self) -> ProtoServiceVersioningRule:
        return ProtoServiceVersioningRule()

    def test_skip_no_evidence(self, rule: ProtoServiceVersioningRule) -> None:
        result = rule.evaluate([], None)
        assert result.skipped is True
        assert result.rule_id == "proto-service-versioning"

    def test_unversioned_amber(self, rule: ProtoServiceVersioningRule) -> None:
        evidence = _make_evidence(
            services=[
                {
                    "name": "CartService",
                    "line": 5,
                    "has_comment": True,
                    "methods": [],
                }
            ],
            package="shop.cart",
        )
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(amber) == 1
        assert "CartService" in amber[0].summary

    def test_versioned_service_name_green(self, rule: ProtoServiceVersioningRule) -> None:
        evidence = _make_evidence(
            services=[
                {
                    "name": "CartServiceV1",
                    "line": 5,
                    "has_comment": True,
                    "methods": [],
                }
            ],
            package="shop.cart",
        )
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        assert all(f.rag == "green" for f in result.findings)

    def test_versioned_package_green(self, rule: ProtoServiceVersioningRule) -> None:
        evidence = _make_evidence(
            services=[
                {
                    "name": "CartService",
                    "line": 5,
                    "has_comment": True,
                    "methods": [],
                }
            ],
            package="shop.cart.v1",
        )
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        assert all(f.rag == "green" for f in result.findings)

    def test_no_services_green(self, rule: ProtoServiceVersioningRule) -> None:
        evidence = _make_evidence(services=[], package="shop")
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        assert all(f.rag == "green" for f in result.findings)

    def test_mixed_versioned_and_not(self, rule: ProtoServiceVersioningRule) -> None:
        evidence = _make_evidence(
            services=[
                {"name": "CartServiceV2", "line": 5, "has_comment": True, "methods": []},
                {"name": "ProductService", "line": 15, "has_comment": True, "methods": []},
            ],
            package="shop",
        )
        result = rule.evaluate(evidence, None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(amber) == 1
        assert "ProductService" in amber[0].summary

    def test_case_insensitive_version_suffix(self, rule: ProtoServiceVersioningRule) -> None:
        evidence = _make_evidence(
            services=[
                {"name": "Servicev2", "line": 1, "has_comment": False, "methods": []},
            ],
            package="test",
        )
        result = rule.evaluate(evidence, None)
        assert all(f.rag == "green" for f in result.findings)

    def test_finding_fields_match_r007(self, rule: ProtoServiceVersioningRule) -> None:
        evidence = _make_evidence(
            services=[
                {"name": "Svc", "line": 1, "has_comment": False, "methods": []},
            ],
        )
        result = rule.evaluate(evidence, None)
        finding = result.findings[0]
        assert finding.rule_id == "proto-service-versioning"
        assert finding.pattern_tag == "proto-service-versioning"
        assert finding.collector_name == "proto"


# ---------------------------------------------------------------------------
# ProtoMethodCommentsRule
# ---------------------------------------------------------------------------


class TestMethodComments:
    @pytest.fixture()
    def rule(self) -> ProtoMethodCommentsRule:
        return ProtoMethodCommentsRule()

    def test_skip_no_evidence(self, rule: ProtoMethodCommentsRule) -> None:
        result = rule.evaluate([], None)
        assert result.skipped is True
        assert result.rule_id == "proto-method-comments"

    def test_all_commented_green(self, rule: ProtoMethodCommentsRule) -> None:
        evidence = _make_evidence(
            services=[
                {
                    "name": "CartService",
                    "line": 5,
                    "has_comment": True,
                    "methods": [
                        {
                            "name": "AddItem",
                            "request_type": "AddItemRequest",
                            "response_type": "Empty",
                            "line": 7,
                            "has_comment": True,
                        },
                        {
                            "name": "GetCart",
                            "request_type": "GetCartRequest",
                            "response_type": "Cart",
                            "line": 10,
                            "has_comment": True,
                        },
                    ],
                }
            ]
        )
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        assert all(f.rag == "green" for f in result.findings)

    def test_uncommented_method_amber(self, rule: ProtoMethodCommentsRule) -> None:
        evidence = _make_evidence(
            services=[
                {
                    "name": "CartService",
                    "line": 5,
                    "has_comment": True,
                    "methods": [
                        {
                            "name": "AddItem",
                            "request_type": "AddItemRequest",
                            "response_type": "Empty",
                            "line": 7,
                            "has_comment": True,
                        },
                        {
                            "name": "EmptyCart",
                            "request_type": "EmptyCartRequest",
                            "response_type": "Empty",
                            "line": 12,
                            "has_comment": False,
                        },
                    ],
                }
            ]
        )
        result = rule.evaluate(evidence, None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(amber) == 1
        assert "EmptyCart" in amber[0].summary
        assert "CartService" in amber[0].summary

    def test_empty_service_green(self, rule: ProtoMethodCommentsRule) -> None:
        evidence = _make_evidence(
            services=[
                {
                    "name": "EmptyService",
                    "line": 1,
                    "has_comment": True,
                    "methods": [],
                }
            ]
        )
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        assert all(f.rag == "green" for f in result.findings)

    def test_no_services_green(self, rule: ProtoMethodCommentsRule) -> None:
        evidence = _make_evidence(services=[])
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        assert all(f.rag == "green" for f in result.findings)

    def test_multiple_uncommented_methods(self, rule: ProtoMethodCommentsRule) -> None:
        evidence = _make_evidence(
            services=[
                {
                    "name": "Svc",
                    "line": 1,
                    "has_comment": False,
                    "methods": [
                        {
                            "name": "A",
                            "request_type": "Req",
                            "response_type": "Resp",
                            "line": 2,
                            "has_comment": False,
                        },
                        {
                            "name": "B",
                            "request_type": "Req",
                            "response_type": "Resp",
                            "line": 4,
                            "has_comment": False,
                        },
                    ],
                }
            ]
        )
        result = rule.evaluate(evidence, None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(amber) == 2

    def test_finding_fields_match_r007(self, rule: ProtoMethodCommentsRule) -> None:
        evidence = _make_evidence(
            services=[
                {
                    "name": "Svc",
                    "line": 1,
                    "has_comment": False,
                    "methods": [
                        {
                            "name": "M",
                            "request_type": "R",
                            "response_type": "R",
                            "line": 2,
                            "has_comment": False,
                        },
                    ],
                }
            ]
        )
        result = rule.evaluate(evidence, None)
        finding = result.findings[0]
        assert finding.rule_id == "proto-method-comments"
        assert finding.pattern_tag == "proto-method-comments"
        assert finding.collector_name == "proto"
        assert finding.severity == "low"
