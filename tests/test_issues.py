# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for nfr_review.issues — sync_issues and supporting functions."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from nfr_review.issues import (
    _CLOSED_BY_TOOL_MARKER,
    _KEY_MARKER_PREFIX,
    _MARKER_SUFFIX,
    _RAG_MARKER_PREFIX,
    _RULE_MARKER_PREFIX,
    _extract_key,
    _finding_key,
    filter_findings,
    generate_issue_body,
    generate_issue_title,
    issue_labels,
    sync_issues,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_RED_CRITICAL: dict[str, Any] = {
    "rule_id": "R001",
    "rag": "red",
    "severity": "critical",
    "summary": "No circuit breaker configured",
    "recommendation": "Add resilience4j or equivalent",
    "evidence_locator": "src/main/java/App.java:42",
    "collector_name": "java_ast",
    "confidence": 0.9,
    "pattern_tag": "resilience",
}

_RED_HIGH: dict[str, Any] = {
    "rule_id": "R010",
    "rag": "red",
    "severity": "high",
    "summary": "Missing retry policy on HTTP client",
    "recommendation": "Configure retry with exponential backoff",
    "evidence_locator": "src/main/java/HttpClient.java:15",
    "collector_name": "java_ast",
    "confidence": 0.85,
    "pattern_tag": "resilience",
}

_RED_MEDIUM: dict[str, Any] = {
    "rule_id": "R020",
    "rag": "red",
    "severity": "medium",
    "summary": "Thread pool size not bounded",
    "recommendation": "Set explicit thread pool limits",
    "evidence_locator": "src/main/resources/application.yaml",
    "collector_name": "spring_config",
    "confidence": 0.7,
    "pattern_tag": "concurrency",
}

_AMBER_HIGH: dict[str, Any] = {
    "rule_id": "R002",
    "rag": "amber",
    "severity": "high",
    "summary": "Thread pool size not explicitly set",
    "recommendation": "Set explicit thread pool bounds",
    "evidence_locator": "src/main/resources/application.yaml",
    "collector_name": "spring_config",
    "confidence": 0.7,
    "pattern_tag": "concurrency",
}

_GREEN_INFO: dict[str, Any] = {
    "rule_id": "R003",
    "rag": "green",
    "severity": "info",
    "summary": "Health endpoint present",
    "recommendation": "",
    "evidence_locator": "src/main/java/Health.java",
    "collector_name": "java_ast",
    "confidence": 1.0,
    "pattern_tag": "observability",
}


def _gh_result(stdout: str = "", returncode: int = 0) -> MagicMock:
    m = MagicMock()
    m.stdout = stdout
    m.returncode = returncode
    return m


def _issue_json(
    number: int,
    body: str,
    state: str = "OPEN",
    url: str = "",
) -> dict[str, Any]:
    return {
        "number": number,
        "body": body,
        "state": state,
        "url": url or f"https://github.com/o/r/issues/{number}",
    }


def _make_body_with_key(key: str, rule_id: str = "R001", rag: str = "red") -> str:
    return (
        f"{_KEY_MARKER_PREFIX}{key}{_MARKER_SUFFIX}\n"
        f"{_RULE_MARKER_PREFIX}{rule_id}{_MARKER_SUFFIX}\n"
        f"{_RAG_MARKER_PREFIX}{rag}{_MARKER_SUFFIX}\n"
        "rest of body\n"
    )


# ---------------------------------------------------------------------------
# filter_findings
# ---------------------------------------------------------------------------


class TestFilterFindings:
    def test_default_rag_min_red_only(self) -> None:
        filtered = filter_findings([_RED_CRITICAL, _AMBER_HIGH, _GREEN_INFO])
        assert len(filtered) == 1
        assert filtered[0]["rule_id"] == "R001"

    def test_rag_min_amber_includes_amber_and_red(self) -> None:
        filtered = filter_findings([_RED_CRITICAL, _AMBER_HIGH, _GREEN_INFO], rag_min="amber")
        assert {f["rule_id"] for f in filtered} == {"R001", "R002"}

    def test_rag_min_red_excludes_amber(self) -> None:
        filtered = filter_findings([_AMBER_HIGH, _GREEN_INFO], rag_min="red")
        assert filtered == []

    def test_severity_threshold_critical(self) -> None:
        filtered = filter_findings(
            [_RED_CRITICAL, _RED_HIGH, _RED_MEDIUM],
            "critical",
        )
        assert len(filtered) == 1
        assert filtered[0]["rule_id"] == "R001"

    def test_severity_threshold_medium(self) -> None:
        filtered = filter_findings(
            [_RED_CRITICAL, _RED_HIGH, _RED_MEDIUM],
            "medium",
        )
        assert len(filtered) == 3

    def test_empty_input(self) -> None:
        assert filter_findings([]) == []


# ---------------------------------------------------------------------------
# generate_issue_title
# ---------------------------------------------------------------------------


class TestGenerateIssueTitle:
    def test_basic_title(self) -> None:
        title = generate_issue_title(_RED_CRITICAL)
        assert title == "[nfr-review] R001: No circuit breaker configured"

    def test_long_summary_truncated_at_60(self) -> None:
        finding = {**_RED_CRITICAL, "summary": "A" * 80}
        title = generate_issue_title(finding)
        summary_part = title.split(": ", 1)[1]
        assert len(summary_part) <= 60
        assert summary_part.endswith("...")

    def test_missing_fields(self) -> None:
        title = generate_issue_title({})
        assert title.startswith("[nfr-review] UNKNOWN:")


# ---------------------------------------------------------------------------
# generate_issue_body
# ---------------------------------------------------------------------------


class TestGenerateIssueBody:
    def test_contains_three_markers(self) -> None:
        body = generate_issue_body(_RED_CRITICAL)
        assert _KEY_MARKER_PREFIX in body
        assert _RULE_MARKER_PREFIX in body
        assert _RAG_MARKER_PREFIX in body

    def test_key_marker_contains_fingerprint(self) -> None:
        body = generate_issue_body(_RED_CRITICAL)
        key = _finding_key(_RED_CRITICAL)
        assert f"{_KEY_MARKER_PREFIX}{key}{_MARKER_SUFFIX}" in body

    def test_rule_marker(self) -> None:
        body = generate_issue_body(_RED_CRITICAL)
        assert f"{_RULE_MARKER_PREFIX}R001{_MARKER_SUFFIX}" in body

    def test_rag_marker(self) -> None:
        body = generate_issue_body(_RED_CRITICAL)
        assert f"{_RAG_MARKER_PREFIX}red{_MARKER_SUFFIX}" in body

    def test_contains_severity_in_table(self) -> None:
        body = generate_issue_body(_RED_CRITICAL)
        assert "| **Severity** | `critical` |" in body

    def test_contains_summary_section(self) -> None:
        body = generate_issue_body(_RED_CRITICAL)
        assert "### Summary" in body
        assert "No circuit breaker configured" in body

    def test_contains_recommendation(self) -> None:
        body = generate_issue_body(_RED_CRITICAL)
        assert "### Recommendation" in body
        assert "resilience4j" in body

    def test_no_recommendation_when_empty(self) -> None:
        finding = {**_RED_CRITICAL, "recommendation": ""}
        body = generate_issue_body(finding)
        assert "### Recommendation" not in body

    def test_contains_evidence(self) -> None:
        body = generate_issue_body(_RED_CRITICAL)
        assert "`src/main/java/App.java:42`" in body

    def test_contains_footer(self) -> None:
        body = generate_issue_body(_RED_CRITICAL)
        assert "Filed automatically by" in body

    def test_ends_with_newline(self) -> None:
        body = generate_issue_body(_RED_CRITICAL)
        assert body.endswith("\n")


# ---------------------------------------------------------------------------
# _extract_key
# ---------------------------------------------------------------------------


class TestExtractKey:
    def test_new_format(self) -> None:
        body = f"{_KEY_MARKER_PREFIX}abc123def456{_MARKER_SUFFIX}\nrest"
        assert _extract_key(body) == "abc123def456"

    def test_legacy_format(self) -> None:
        body = "<!-- nfr-review:issue:abc123def456 -->\nrest"
        assert _extract_key(body) == "abc123def456"

    def test_no_marker(self) -> None:
        assert _extract_key("no marker here") is None


# ---------------------------------------------------------------------------
# issue_labels
# ---------------------------------------------------------------------------


class TestIssueLabels:
    def test_base_labels(self) -> None:
        labels = issue_labels(_RED_CRITICAL)
        assert "nfr-review" in labels
        assert "severity:critical" in labels

    def test_extra_labels(self) -> None:
        labels = issue_labels(_RED_CRITICAL, extra_labels=["team:platform", "sprint:5"])
        assert "team:platform" in labels
        assert "sprint:5" in labels
        assert "nfr-review" in labels

    def test_no_extra_labels(self) -> None:
        labels = issue_labels(_RED_CRITICAL, extra_labels=None)
        assert len(labels) == 2


# ---------------------------------------------------------------------------
# sync_issues — create
# ---------------------------------------------------------------------------


class TestSyncCreate:
    def test_new_finding_creates_issue(self) -> None:
        with (
            patch("nfr_review.issues._fetch_nfr_issues", return_value=[]),
            patch("nfr_review.issues._gh_run") as gh,
        ):
            gh.return_value = _gh_result("https://github.com/o/r/issues/1")
            results = sync_issues([_RED_CRITICAL], "owner/repo", rag_min="red")

        assert len(results) == 1
        assert results[0]["action"] == "create"
        assert results[0]["url"] == "https://github.com/o/r/issues/1"

    def test_create_uses_correct_title_and_body(self) -> None:
        with (
            patch("nfr_review.issues._fetch_nfr_issues", return_value=[]),
            patch("nfr_review.issues._gh_run") as gh,
        ):
            gh.return_value = _gh_result("https://github.com/o/r/issues/1")
            sync_issues([_RED_CRITICAL], "owner/repo", rag_min="red")

        create_call = gh.call_args
        args = create_call[0][0]
        assert "--title" in args
        title_idx = args.index("--title")
        assert args[title_idx + 1].startswith("[nfr-review]")

    def test_create_includes_labels(self) -> None:
        with (
            patch("nfr_review.issues._fetch_nfr_issues", return_value=[]),
            patch("nfr_review.issues._gh_run") as gh,
        ):
            gh.return_value = _gh_result("https://github.com/o/r/issues/1")
            sync_issues(
                [_RED_CRITICAL],
                "owner/repo",
                rag_min="red",
                extra_labels=["team:infra"],
            )

        args = gh.call_args[0][0]
        label_values = [args[i + 1] for i, a in enumerate(args) if a == "--label"]
        assert "nfr-review" in label_values
        assert "severity:critical" in label_values
        assert "team:infra" in label_values


# ---------------------------------------------------------------------------
# sync_issues — update
# ---------------------------------------------------------------------------


class TestSyncUpdate:
    def test_existing_open_issue_gets_updated(self) -> None:
        key = _finding_key(_RED_CRITICAL)
        old_body = _make_body_with_key(key)
        issues = [_issue_json(42, old_body)]

        with (
            patch("nfr_review.issues._fetch_nfr_issues", return_value=issues),
            patch("nfr_review.issues._gh_run") as gh,
        ):
            gh.return_value = _gh_result()
            results = sync_issues([_RED_CRITICAL], "owner/repo", rag_min="red")

        assert len(results) == 1
        assert results[0]["action"] == "update"
        assert results[0]["reason"] == "body updated"


# ---------------------------------------------------------------------------
# sync_issues — idempotency
# ---------------------------------------------------------------------------


class TestSyncIdempotent:
    def test_identical_body_produces_unchanged(self) -> None:
        current_body = generate_issue_body(_RED_CRITICAL)
        issues = [_issue_json(42, current_body)]

        with (
            patch("nfr_review.issues._fetch_nfr_issues", return_value=issues),
            patch("nfr_review.issues._gh_run") as gh,
        ):
            results = sync_issues([_RED_CRITICAL], "owner/repo", rag_min="red")

        assert len(results) == 1
        assert results[0]["action"] == "unchanged"
        gh.assert_not_called()


# ---------------------------------------------------------------------------
# sync_issues — close-resolved
# ---------------------------------------------------------------------------


class TestSyncClose:
    def test_open_issue_without_matching_finding_gets_closed(self) -> None:
        key = _finding_key(_RED_CRITICAL)
        body = _make_body_with_key(key)
        issues = [_issue_json(42, body)]

        with (
            patch("nfr_review.issues._fetch_nfr_issues", return_value=issues),
            patch("nfr_review.issues._gh_run") as gh,
        ):
            gh.return_value = _gh_result()
            results = sync_issues([], "owner/repo", rag_min="red")

        assert len(results) == 1
        assert results[0]["action"] == "close"
        assert results[0]["reason"] == "finding no longer present"
        close_call = gh.call_args
        args = close_call[0][0]
        assert "close" in args
        comment_idx = args.index("--comment")
        assert _CLOSED_BY_TOOL_MARKER in args[comment_idx + 1]

    def test_close_resolved_disabled(self) -> None:
        key = _finding_key(_RED_CRITICAL)
        body = _make_body_with_key(key)
        issues = [_issue_json(42, body)]

        with (
            patch("nfr_review.issues._fetch_nfr_issues", return_value=issues),
            patch("nfr_review.issues._gh_run") as gh,
        ):
            results = sync_issues([], "owner/repo", rag_min="red", close_resolved=False)

        assert results == []
        gh.assert_not_called()


# ---------------------------------------------------------------------------
# sync_issues — manual close preservation
# ---------------------------------------------------------------------------


class TestSyncManualClose:
    def test_manually_closed_issue_not_recreated(self) -> None:
        key = _finding_key(_RED_CRITICAL)
        body = _make_body_with_key(key)
        closed_issue = _issue_json(42, body, state="CLOSED")

        with (
            patch("nfr_review.issues._fetch_nfr_issues", return_value=[closed_issue]),
            patch("nfr_review.issues._issue_has_tool_close_comment", return_value=False),
        ):
            results = sync_issues([_RED_CRITICAL], "owner/repo", rag_min="red")

        assert len(results) == 1
        assert results[0]["action"] == "skip"
        assert results[0]["reason"] == "manually closed"

    def test_tool_closed_issue_gets_recreated(self) -> None:
        key = _finding_key(_RED_CRITICAL)
        body = _make_body_with_key(key)
        closed_issue = _issue_json(42, body, state="CLOSED")

        with (
            patch("nfr_review.issues._fetch_nfr_issues", return_value=[closed_issue]),
            patch("nfr_review.issues._issue_has_tool_close_comment", return_value=True),
            patch("nfr_review.issues._gh_run") as gh,
        ):
            gh.return_value = _gh_result("https://github.com/o/r/issues/99")
            results = sync_issues([_RED_CRITICAL], "owner/repo", rag_min="red")

        assert len(results) == 1
        assert results[0]["action"] == "create"


# ---------------------------------------------------------------------------
# sync_issues — first-run cap
# ---------------------------------------------------------------------------


class TestSyncFirstRunCap:
    def test_caps_creation_on_first_run(self) -> None:
        findings = [
            {**_RED_CRITICAL, "evidence_locator": f"file{i}.java:1"} for i in range(30)
        ]

        with (
            patch("nfr_review.issues._fetch_nfr_issues", return_value=[]),
            patch("nfr_review.issues._gh_run") as gh,
        ):
            gh.return_value = _gh_result("https://github.com/o/r/issues/1")
            results = sync_issues(
                findings,
                "owner/repo",
                rag_min="red",
                first_run_cap=10,
            )

        created = [r for r in results if r["action"] == "create"]
        skipped = [r for r in results if r["action"] == "skip"]
        assert len(created) == 10
        assert len(skipped) == 20
        assert all("first-run cap" in r["reason"] for r in skipped)

    def test_no_cap_when_issues_exist(self) -> None:
        existing_body = _make_body_with_key("existingkey1")
        existing_issues = [_issue_json(1, existing_body)]
        findings = [{**_RED_CRITICAL, "evidence_locator": f"file{i}.java:1"} for i in range(5)]

        with (
            patch("nfr_review.issues._fetch_nfr_issues", return_value=existing_issues),
            patch("nfr_review.issues._gh_run") as gh,
        ):
            gh.return_value = _gh_result("https://github.com/o/r/issues/99")
            results = sync_issues(
                findings,
                "owner/repo",
                rag_min="red",
                first_run_cap=2,
            )

        created = [r for r in results if r["action"] == "create"]
        assert len(created) == 5


# ---------------------------------------------------------------------------
# sync_issues — dry-run
# ---------------------------------------------------------------------------


class TestSyncDryRun:
    def test_dry_run_no_api_calls(self) -> None:
        with (
            patch("nfr_review.issues._fetch_nfr_issues", return_value=[]) as fetch,
            patch("nfr_review.issues._gh_run") as gh,
        ):
            results = sync_issues(
                [_RED_CRITICAL, _RED_HIGH],
                "owner/repo",
                dry_run=True,
                rag_min="red",
            )

        assert len(results) == 2
        assert all(r["action"] == "create" for r in results)
        fetch.assert_called_once()
        gh.assert_not_called()

    def test_dry_run_reports_create_update_close(self) -> None:
        key_crit = _finding_key(_RED_CRITICAL)
        key_old = "oldkey123456"
        open_issues = [
            _issue_json(1, _make_body_with_key(key_crit)),
            _issue_json(2, _make_body_with_key(key_old)),
        ]

        with (
            patch("nfr_review.issues._fetch_nfr_issues", return_value=open_issues),
            patch("nfr_review.issues._gh_run") as gh,
        ):
            results = sync_issues(
                [_RED_CRITICAL],
                "owner/repo",
                dry_run=True,
                rag_min="red",
            )

        actions = {r["action"] for r in results}
        assert "update" in actions or "unchanged" in actions
        assert "close" in actions
        gh.assert_not_called()


# ---------------------------------------------------------------------------
# sync_issues — RAG filter integration
# ---------------------------------------------------------------------------


class TestSyncRagFilter:
    def test_amber_included_with_rag_min_amber(self) -> None:
        with (
            patch("nfr_review.issues._fetch_nfr_issues", return_value=[]),
            patch("nfr_review.issues._gh_run") as gh,
        ):
            gh.return_value = _gh_result("https://github.com/o/r/issues/1")
            results = sync_issues(
                [_RED_CRITICAL, _AMBER_HIGH],
                "owner/repo",
                rag_min="amber",
            )

        assert len(results) == 2
        assert all(r["action"] == "create" for r in results)

    def test_amber_excluded_with_rag_min_red(self) -> None:
        with (
            patch("nfr_review.issues._fetch_nfr_issues", return_value=[]),
            patch("nfr_review.issues._gh_run") as gh,
        ):
            gh.return_value = _gh_result("https://github.com/o/r/issues/1")
            results = sync_issues(
                [_RED_CRITICAL, _AMBER_HIGH],
                "owner/repo",
                rag_min="red",
            )

        assert len(results) == 1
        assert results[0]["rule_id"] == "R001"
