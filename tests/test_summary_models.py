# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for executive-summary Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from nfr_review.output.summary_models import ExecSummary, RemediationItem

# -- helpers ------------------------------------------------------------------


def _make_remediation(**overrides: object) -> dict:
    defaults: dict[str, object] = {
        "title": "Fix memory leak",
        "urgency": "immediate",
        "description": "Plug the leak in allocator.",
    }
    defaults.update(overrides)
    return defaults


def _make_summary(**overrides: object) -> dict:
    defaults: dict[str, object] = {
        "verdict": "conditional",
        "verdict_explanation": "Needs work before production.",
        "risk_highlights": ["memory leak", "no TLS"],
        "remediation_priorities": [_make_remediation()],
        "production_risks": "High memory usage under load.",
        "open_source_readiness": "License headers missing.",
        "overall_score": 65,
    }
    defaults.update(overrides)
    return defaults


# -- RemediationItem ----------------------------------------------------------


class TestRemediationItem:
    def test_valid_construction(self) -> None:
        item = RemediationItem(**_make_remediation())
        assert item.title == "Fix memory leak"
        assert item.urgency == "immediate"
        assert item.description == "Plug the leak in allocator."

    @pytest.mark.parametrize("urgency", ["immediate", "short-term", "medium-term"])
    def test_all_valid_urgency_values(self, urgency: str) -> None:
        item = RemediationItem(**_make_remediation(urgency=urgency))
        assert item.urgency == urgency

    def test_invalid_urgency_rejected(self) -> None:
        with pytest.raises(ValidationError, match="urgency"):
            RemediationItem(**_make_remediation(urgency="long-term"))

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError, match="extra"):
            RemediationItem(**_make_remediation(priority=1))

    def test_model_dump_round_trip(self) -> None:
        item = RemediationItem(**_make_remediation())
        dumped = item.model_dump()
        restored = RemediationItem(**dumped)
        assert restored == item


# -- ExecSummary --------------------------------------------------------------


class TestExecSummary:
    def test_valid_construction(self) -> None:
        summary = ExecSummary(**_make_summary())
        assert summary.verdict == "conditional"
        assert summary.overall_score == 65
        assert len(summary.remediation_priorities) == 1
        assert isinstance(summary.remediation_priorities[0], RemediationItem)

    @pytest.mark.parametrize("verdict", ["fit", "conditional", "unfit"])
    def test_all_valid_verdict_values(self, verdict: str) -> None:
        summary = ExecSummary(**_make_summary(verdict=verdict))
        assert summary.verdict == verdict

    def test_invalid_verdict_rejected(self) -> None:
        with pytest.raises(ValidationError, match="verdict"):
            ExecSummary(**_make_summary(verdict="maybe"))

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError, match="extra"):
            ExecSummary(**_make_summary(bonus_field="nope"))

    def test_score_boundary_zero(self) -> None:
        summary = ExecSummary(**_make_summary(overall_score=0))
        assert summary.overall_score == 0

    def test_score_boundary_hundred(self) -> None:
        summary = ExecSummary(**_make_summary(overall_score=100))
        assert summary.overall_score == 100

    def test_score_below_zero_rejected(self) -> None:
        with pytest.raises(ValidationError, match="overall_score"):
            ExecSummary(**_make_summary(overall_score=-1))

    def test_score_above_hundred_rejected(self) -> None:
        with pytest.raises(ValidationError, match="overall_score"):
            ExecSummary(**_make_summary(overall_score=101))

    def test_defaults_for_list_fields(self) -> None:
        summary = ExecSummary(
            verdict="fit",
            verdict_explanation="All good.",
            production_risks="None.",
            open_source_readiness="Ready.",
            overall_score=95,
        )
        assert summary.risk_highlights == []
        assert summary.remediation_priorities == []

    def test_model_dump_round_trip(self) -> None:
        summary = ExecSummary(**_make_summary())
        dumped = summary.model_dump()
        restored = ExecSummary(**dumped)
        assert restored == summary

    def test_nested_remediation_validated(self) -> None:
        bad_item = _make_remediation(urgency="wrong")
        with pytest.raises(ValidationError):
            ExecSummary(**_make_summary(remediation_priorities=[bad_item]))
