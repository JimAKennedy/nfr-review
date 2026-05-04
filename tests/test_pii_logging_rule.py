"""Tests for PiiInLogStatementsRule — regex pre-filter + LLM confirmation paths."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from nfr_review.llm_client import ClaudeClient, LlmUnavailableError
from nfr_review.models import Evidence
from nfr_review.rules.pii_logging import PiiInLogStatementsRule


def _make_evidence(
    log_statements: list[dict] | None = None,
    file_path: str = "src/main/java/com/example/App.java",
) -> Evidence:
    return Evidence(
        collector_name="java-ast",
        collector_version="0.1.0",
        locator=file_path,
        kind="java-ast-file",
        payload={
            "file_path": file_path,
            "classes": [],
            "methods": [],
            "catch_blocks": [],
            "imports": [],
            "thread_pool_constructions": [],
            "log_statements": log_statements or [],
        },
    )


def _unavailable_client() -> ClaudeClient:
    client = MagicMock(spec=ClaudeClient)
    client.available = False
    client.analyze.side_effect = LlmUnavailableError("no key")
    return client


def _confirming_client(verdicts: list[dict]) -> ClaudeClient:
    client = MagicMock(spec=ClaudeClient)
    client.available = True
    client.analyze.return_value = json.dumps(verdicts)
    return client


class TestNoEvidence:
    def test_no_evidence_skipped(self) -> None:
        rule = PiiInLogStatementsRule(llm_client=_unavailable_client())
        result = rule.evaluate([], context=None)
        assert result.skipped is True
        assert "no java-ast evidence" in (result.skip_reason or "")

    def test_non_java_evidence_skipped(self) -> None:
        ev = Evidence(
            collector_name="config-file",
            collector_version="0.1.0",
            locator="app.yml",
            kind="config-file",
            payload={},
        )
        rule = PiiInLogStatementsRule(llm_client=_unavailable_client())
        result = rule.evaluate([ev], context=None)
        assert result.skipped is True


class TestNoLogStatements:
    def test_no_log_statements_green(self) -> None:
        ev = _make_evidence(log_statements=[])
        rule = PiiInLogStatementsRule(llm_client=_unavailable_client())
        result = rule.evaluate([ev], context=None)
        assert result.skipped is True

    def test_java_evidence_without_log_field_skipped(self) -> None:
        ev = Evidence(
            collector_name="java-ast",
            collector_version="0.1.0",
            locator="App.java",
            kind="java-ast-file",
            payload={"file_path": "App.java", "log_statements": []},
        )
        rule = PiiInLogStatementsRule(llm_client=_unavailable_client())
        result = rule.evaluate([ev], context=None)
        assert result.skipped is True


class TestRegexMatchNoLlm:
    def test_regex_match_no_llm_available(self) -> None:
        ev = _make_evidence(
            log_statements=[
                {
                    "method": "logger.info",
                    "arguments_text": '("User SSN: 123-45-6789", userId)',
                    "line": 10,
                }
            ]
        )
        rule = PiiInLogStatementsRule(llm_client=_unavailable_client())
        result = rule.evaluate([ev], context=None)
        assert not result.skipped
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.confidence == 0.6
        assert f.rag == "amber"
        assert "ssn" in f.summary
        assert "LLM confirmation unavailable" in f.summary

    def test_email_pattern_detected(self) -> None:
        ev = _make_evidence(
            log_statements=[
                {
                    "method": "logger.info",
                    "arguments_text": '("User email: {}", email)',
                    "line": 5,
                }
            ]
        )
        rule = PiiInLogStatementsRule(llm_client=_unavailable_client())
        result = rule.evaluate([ev], context=None)
        assert len(result.findings) == 1
        assert result.findings[0].confidence == 0.6

    def test_credit_card_pattern_detected(self) -> None:
        ev = _make_evidence(
            log_statements=[
                {
                    "method": "logger.warn",
                    "arguments_text": '("Card: 4111-1111-1111-1111")',
                    "line": 7,
                }
            ]
        )
        rule = PiiInLogStatementsRule(llm_client=_unavailable_client())
        result = rule.evaluate([ev], context=None)
        assert len(result.findings) == 1
        assert "credit_card" in result.findings[0].summary

    def test_secret_variable_detected(self) -> None:
        ev = _make_evidence(
            log_statements=[
                {
                    "method": "logger.debug",
                    "arguments_text": '("Auth token: {}", token)',
                    "line": 12,
                }
            ]
        )
        rule = PiiInLogStatementsRule(llm_client=_unavailable_client())
        result = rule.evaluate([ev], context=None)
        assert len(result.findings) == 1
        assert "secret_variable" in result.findings[0].summary


class TestLlmConfirms:
    def test_regex_match_llm_confirms(self) -> None:
        ev = _make_evidence(
            log_statements=[
                {
                    "method": "logger.info",
                    "arguments_text": '("User SSN: 123-45-6789", ssn)',
                    "line": 10,
                }
            ]
        )
        llm = _confirming_client([{"index": 0, "is_pii": True, "reason": "SSN value logged"}])
        rule = PiiInLogStatementsRule(llm_client=llm)
        result = rule.evaluate([ev], context=None)
        assert not result.skipped
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.confidence == 0.85
        assert f.rag == "red"
        assert f.severity == "high"
        assert "SSN value logged" in f.summary

    def test_regex_match_llm_denies(self) -> None:
        ev = _make_evidence(
            log_statements=[
                {
                    "method": "logger.info",
                    "arguments_text": '("Processing email notification")',
                    "line": 15,
                }
            ]
        )
        llm = _confirming_client([{"index": 0, "is_pii": False, "reason": "not actual PII"}])
        rule = PiiInLogStatementsRule(llm_client=llm)
        result = rule.evaluate([ev], context=None)
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.confidence == 0.4
        assert f.rag == "amber"
        assert "not actual PII" in f.summary


class TestNoRegexMatch:
    def test_no_regex_match_green(self) -> None:
        ev = _make_evidence(
            log_statements=[
                {
                    "method": "logger.info",
                    "arguments_text": '("Order processed successfully")',
                    "line": 20,
                }
            ]
        )
        rule = PiiInLogStatementsRule(llm_client=_unavailable_client())
        result = rule.evaluate([ev], context=None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert result.findings[0].confidence == 0.85


class TestMultipleFiles:
    def test_multiple_files_aggregation(self) -> None:
        ev1 = _make_evidence(
            log_statements=[
                {
                    "method": "logger.info",
                    "arguments_text": '("User SSN: 123-45-6789")',
                    "line": 10,
                }
            ],
            file_path="src/UserService.java",
        )
        ev2 = _make_evidence(
            log_statements=[
                {
                    "method": "LOG.warn",
                    "arguments_text": '("Password reset for {}", password)',
                    "line": 25,
                }
            ],
            file_path="src/AuthService.java",
        )
        rule = PiiInLogStatementsRule(llm_client=_unavailable_client())
        result = rule.evaluate([ev1, ev2], context=None)
        assert not result.skipped
        assert len(result.findings) == 2
        locators = [f.evidence_locator for f in result.findings]
        assert "src/UserService.java:10" in locators
        assert "src/AuthService.java:25" in locators


class TestLlmErrorFallback:
    def test_llm_api_error_falls_back_to_regex(self) -> None:
        ev = _make_evidence(
            log_statements=[
                {
                    "method": "logger.info",
                    "arguments_text": '("User SSN: 123-45-6789")',
                    "line": 10,
                }
            ]
        )
        llm = MagicMock(spec=ClaudeClient)
        llm.available = True
        llm.analyze.side_effect = RuntimeError("API timeout")
        rule = PiiInLogStatementsRule(llm_client=llm)
        result = rule.evaluate([ev], context=None)
        assert len(result.findings) == 1
        assert result.findings[0].confidence == 0.6

    def test_llm_malformed_response_falls_back(self) -> None:
        ev = _make_evidence(
            log_statements=[
                {
                    "method": "logger.info",
                    "arguments_text": '("User SSN: 123-45-6789")',
                    "line": 10,
                }
            ]
        )
        llm = MagicMock(spec=ClaudeClient)
        llm.available = True
        llm.analyze.return_value = "Sorry, I cannot help with that."
        rule = PiiInLogStatementsRule(llm_client=llm)
        result = rule.evaluate([ev], context=None)
        assert len(result.findings) == 1
        assert result.findings[0].confidence == 0.6
