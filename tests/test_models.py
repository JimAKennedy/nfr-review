from __future__ import annotations

import pytest
from pydantic import ValidationError

from nfr_review.models import (
    Evidence,
    Finding,
    RuleResult,
    RunMetadata,
)

FINDING_FIELD_ORDER = (
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
)


def _valid_finding_payload() -> dict:
    return {
        "rule_id": "sample-readme-exists",
        "rag": "green",
        "severity": "info",
        "summary": "README found at repo root",
        "recommendation": "No action needed",
        "evidence_locator": "README.md",
        "collector_name": "repo_structure",
        "collector_version": "0.1.0",
        "confidence": 0.95,
        "pattern_tag": "documentation",
    }


def test_finding_field_order_matches_r007() -> None:
    """R007 mandates the 10 fields appear in this exact order on disk."""
    assert tuple(Finding.model_fields.keys()) == FINDING_FIELD_ORDER


def test_finding_accepts_valid_payload() -> None:
    f = Finding(**_valid_finding_payload())
    assert f.rule_id == "sample-readme-exists"
    assert f.rag == "green"
    assert f.severity == "info"
    assert f.confidence == 0.95


def test_finding_dump_round_trips_losslessly() -> None:
    payload = _valid_finding_payload()
    f = Finding(**payload)
    dumped = f.model_dump()
    assert dumped == payload
    assert Finding(**dumped) == f


def test_finding_rejects_unknown_rag() -> None:
    payload = _valid_finding_payload()
    payload["rag"] = "purple"
    with pytest.raises(ValidationError):
        Finding(**payload)


def test_finding_rejects_unknown_severity() -> None:
    payload = _valid_finding_payload()
    payload["severity"] = "fatal"
    with pytest.raises(ValidationError):
        Finding(**payload)


def test_finding_accepts_all_rag_values() -> None:
    for rag in ("red", "amber", "green", "skipped"):
        payload = _valid_finding_payload()
        payload["rag"] = rag
        Finding(**payload)


def test_finding_accepts_all_severity_values() -> None:
    for sev in ("critical", "high", "medium", "low", "info"):
        payload = _valid_finding_payload()
        payload["severity"] = sev
        Finding(**payload)


@pytest.mark.parametrize("missing", FINDING_FIELD_ORDER)
def test_finding_requires_every_field(missing: str) -> None:
    payload = _valid_finding_payload()
    payload.pop(missing)
    with pytest.raises(ValidationError):
        Finding(**payload)


def test_finding_confidence_is_bounded() -> None:
    payload = _valid_finding_payload()
    payload["confidence"] = 1.5
    with pytest.raises(ValidationError):
        Finding(**payload)
    payload["confidence"] = -0.1
    with pytest.raises(ValidationError):
        Finding(**payload)


def test_finding_validates_string_types() -> None:
    payload = _valid_finding_payload()
    payload["confidence"] = "not-a-number"
    with pytest.raises(ValidationError):
        Finding(**payload)


def test_finding_rejects_unknown_fields() -> None:
    payload = _valid_finding_payload()
    payload["extra"] = "not allowed"
    with pytest.raises(ValidationError):
        Finding(**payload)


def test_evidence_minimal() -> None:
    e = Evidence(
        collector_name="repo_structure",
        collector_version="0.1.0",
        locator="README.md",
        kind="file",
    )
    assert e.payload == {}


def test_evidence_round_trips() -> None:
    e = Evidence(
        collector_name="repo_structure",
        collector_version="0.1.0",
        locator="src/main/java",
        kind="directory",
        payload={"file_count": 42},
    )
    assert Evidence(**e.model_dump()) == e


def test_rule_result_defaults() -> None:
    r = RuleResult(rule_id="sample")
    assert r.findings == []
    assert r.skipped is False
    assert r.skip_reason is None


def test_rule_result_skipped() -> None:
    r = RuleResult(
        rule_id="sample",
        skipped=True,
        skip_reason="required collector missing",
    )
    assert r.skipped is True
    assert r.skip_reason == "required collector missing"


def test_rule_result_round_trips_with_finding() -> None:
    f = Finding(**_valid_finding_payload())
    r = RuleResult(rule_id="sample-readme-exists", findings=[f])
    dumped = r.model_dump()
    assert RuleResult(**dumped) == r


def test_run_metadata_minimal() -> None:
    m = RunMetadata(
        tool_version="0.1.0",
        target_repo="/tmp/repo",
        timestamp="2026-05-03T12:00:00Z",
    )
    assert m.git_sha is None
    assert m.git_branch is None
    assert m.git_dirty is None
    assert m.git_error is None
    assert m.collector_versions == {}
    assert m.rules_run == []
    assert m.rules_skipped == []


def test_run_metadata_full_round_trip() -> None:
    payload = {
        "tool_version": "0.1.0",
        "target_repo": "/repos/agentic-java-demo",
        "git_sha": "abc1234",
        "git_branch": "main",
        "git_dirty": False,
        "git_error": None,
        "timestamp": "2026-05-03T12:00:00Z",
        "collector_versions": {"repo_structure": "0.1.0"},
        "rules_run": ["sample-readme-exists"],
        "rules_skipped": [
            {"rule_id": "needs-llm", "reason": "ANTHROPIC_API_KEY unset"}
        ],
    }
    m = RunMetadata(**payload)
    assert m.model_dump() == payload
    assert RunMetadata(**m.model_dump()) == m


def test_run_metadata_dirty_flag_accepts_bool() -> None:
    m = RunMetadata(
        tool_version="0.1.0",
        target_repo="/tmp/repo",
        timestamp="2026-05-03T12:00:00Z",
        git_dirty=True,
    )
    assert m.git_dirty is True
