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
    "content_hash",
    "origin",
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
        "content_hash": "",
        "origin": "first_party",
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


_OPTIONAL_FINDING_FIELDS = {"content_hash", "origin"}
_REQUIRED_FINDING_FIELDS = tuple(
    f for f in FINDING_FIELD_ORDER if f not in _OPTIONAL_FINDING_FIELDS
)


@pytest.mark.parametrize("missing", _REQUIRED_FINDING_FIELDS)
def test_finding_requires_every_field(missing: str) -> None:
    payload = _valid_finding_payload()
    payload.pop(missing)
    with pytest.raises(ValidationError):
        Finding(**payload)


def test_content_hash_defaults_to_empty() -> None:
    payload = _valid_finding_payload()
    payload.pop("content_hash")
    f = Finding(**payload)
    assert f.content_hash == ""


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
        "rules_skipped": [{"rule_id": "needs-llm", "reason": "ANTHROPIC_API_KEY unset"}],
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


# ---- Stable identity key (content_hash) ------------------------------------


class TestStableIdentityKey:
    def test_falls_back_to_legacy_without_content_hash(self) -> None:
        f = Finding(**{**_valid_finding_payload(), "evidence_locator": "src/main.py:42"})
        assert f.stable_identity_key == f.identity_key

    def test_strips_line_number_when_content_hash_set(self) -> None:
        f = Finding(
            **{
                **_valid_finding_payload(),
                "evidence_locator": "src/main.py:42",
                "content_hash": "abc123def456",
            }
        )
        assert f.stable_identity_key == (
            "sample-readme-exists",
            "src/main.py",
            "documentation",
            "abc123def456",
        )

    def test_same_content_different_line_same_stable_key(self) -> None:
        base = {**_valid_finding_payload(), "content_hash": "abc123def456"}
        f1 = Finding(**{**base, "evidence_locator": "controller.cpp:140"})
        f2 = Finding(**{**base, "evidence_locator": "controller.cpp:142"})
        assert f1.stable_identity_key == f2.stable_identity_key
        assert f1.identity_key != f2.identity_key

    def test_different_content_same_line_different_stable_key(self) -> None:
        base = {**_valid_finding_payload(), "evidence_locator": "controller.cpp:42"}
        f1 = Finding(**{**base, "content_hash": "hash_aaa"})
        f2 = Finding(**{**base, "content_hash": "hash_bbb"})
        assert f1.stable_identity_key != f2.stable_identity_key

    def test_locator_without_line_number_unchanged(self) -> None:
        f = Finding(
            **{
                **_valid_finding_payload(),
                "evidence_locator": "project-wide",
                "content_hash": "abc123",
            }
        )
        assert f.stable_identity_key == (
            "sample-readme-exists",
            "project-wide",
            "documentation",
            "abc123",
        )


class TestComputeContentHash:
    def test_empty_string_returns_empty(self) -> None:
        from nfr_review.models import compute_content_hash

        assert compute_content_hash("") == ""
        assert compute_content_hash("   ") == ""

    def test_deterministic(self) -> None:
        from nfr_review.models import compute_content_hash

        h1 = compute_content_hash("auto* widget = new CTextLabel(rect)")
        h2 = compute_content_hash("auto* widget = new CTextLabel(rect)")
        assert h1 == h2
        assert len(h1) == 12

    def test_strips_whitespace(self) -> None:
        from nfr_review.models import compute_content_hash

        h1 = compute_content_hash("  code()  ")
        h2 = compute_content_hash("code()")
        assert h1 == h2

    def test_different_content_different_hash(self) -> None:
        from nfr_review.models import compute_content_hash

        h1 = compute_content_hash("new CTextLabel(rect)")
        h2 = compute_content_hash("new CTextButton(rect)")
        assert h1 != h2


class TestStripLineFromLocator:
    def test_strips_line_number(self) -> None:
        from nfr_review.models import _strip_line_from_locator

        assert _strip_line_from_locator("controller.cpp:142") == "controller.cpp"

    def test_preserves_non_line_locator(self) -> None:
        from nfr_review.models import _strip_line_from_locator

        assert _strip_line_from_locator("project-wide") == "project-wide"

    def test_preserves_resource_locator(self) -> None:
        from nfr_review.models import _strip_line_from_locator

        assert (
            _strip_line_from_locator("deployment.yaml:my-pod:container")
            == "deployment.yaml:my-pod:container"
        )

    def test_only_strips_trailing_digits(self) -> None:
        from nfr_review.models import _strip_line_from_locator

        assert _strip_line_from_locator("src/main.py:42") == "src/main.py"
        assert _strip_line_from_locator("a:b:10") == "a:b"
