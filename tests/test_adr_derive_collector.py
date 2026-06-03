# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for the AdrDeriveCollector — LLM-based ADR derivation."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from nfr_review.collectors.adr_derive import AdrDeriveCollector, _extract_json

_VALID_LLM_RESPONSE = json.dumps(
    [
        {
            "title": "Use PostgreSQL for persistence",
            "rationale": "The project uses SQLAlchemy with PostgreSQL drivers.",
            "category": "data",
            "confidence": 0.9,
            "evidence_refs": ["requirements.txt", "docker-compose.yml"],
        },
        {
            "title": "Containerize with Docker",
            "rationale": "Dockerfile present at repo root.",
            "category": "infrastructure",
            "confidence": 0.95,
            "evidence_refs": ["Dockerfile"],
        },
        {
            "title": "Use GitHub Actions for CI/CD",
            "rationale": "Workflow files found under .github/workflows.",
            "category": "deployment",
            "confidence": 0.85,
            "evidence_refs": [".github/workflows/ci.yml"],
        },
    ]
)


def _make_repo(tmp_path: Path) -> Path:
    """Create a minimal fake repo with config files."""
    (tmp_path / "requirements.txt").write_text("flask==2.3.0\nsqlalchemy==2.0.0\n")
    (tmp_path / "Dockerfile").write_text("FROM python:3.11\nCOPY . /app\n")
    (tmp_path / "README.md").write_text("# My Project\n\nA sample project.\n")
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("name: CI\non: push\n")
    return tmp_path


class TestRegistration:
    def test_adr_derive_in_registry(self) -> None:
        from nfr_review.registry import collector_registry

        assert "adr-derive" in collector_registry

    def test_registry_instance_type(self) -> None:
        from nfr_review.registry import collector_registry

        instance = collector_registry.get("adr-derive")
        assert isinstance(instance, AdrDeriveCollector)
        assert instance.name == "adr-derive"
        assert instance.version == "0.1.0"


class TestLlmUnavailable:
    @patch("nfr_review.collectors.adr_derive.create_llm_client")
    def test_returns_skip_evidence_when_llm_unavailable(
        self, mock_cls: MagicMock, tmp_path: Path
    ) -> None:
        mock_client = MagicMock()
        mock_client.available = False
        mock_cls.return_value = mock_client

        collector = AdrDeriveCollector()
        results = collector.collect(_make_repo(tmp_path), config=None)

        assert len(results) == 1
        assert results[0].kind == "adr-derive-skip"
        assert "ANTHROPIC_API_KEY" in results[0].payload["reason"]

    @patch("nfr_review.collectors.adr_derive.create_llm_client")
    def test_skip_evidence_has_correct_collector_info(
        self, mock_cls: MagicMock, tmp_path: Path
    ) -> None:
        mock_client = MagicMock()
        mock_client.available = False
        mock_cls.return_value = mock_client

        collector = AdrDeriveCollector()
        results = collector.collect(_make_repo(tmp_path), config=None)

        assert results[0].collector_name == "adr-derive"
        assert results[0].collector_version == "0.1.0"


class TestJsonExtraction:
    def test_raw_json(self) -> None:
        data = [{"title": "Test", "value": 1}]
        result = _extract_json(json.dumps(data))
        assert result == data

    def test_markdown_wrapped_json(self) -> None:
        data = [{"title": "Test"}]
        text = f"Here is the result:\n\n```json\n{json.dumps(data)}\n```\n\nDone."
        result = _extract_json(text)
        assert result == data

    def test_markdown_fence_without_lang(self) -> None:
        data = [{"title": "Test"}]
        text = f"Result:\n\n```\n{json.dumps(data)}\n```"
        result = _extract_json(text)
        assert result == data

    def test_bare_brackets(self) -> None:
        data = [{"title": "Test"}]
        text = f"Some preamble text\n{json.dumps(data)}\nand trailing text"
        result = _extract_json(text)
        assert result == data

    def test_malformed_text_returns_none(self) -> None:
        assert _extract_json("This is not JSON at all") is None

    def test_empty_string_returns_none(self) -> None:
        assert _extract_json("") is None

    def test_invalid_json_in_fence_returns_none(self) -> None:
        text = "```json\n{not valid json\n```"
        assert _extract_json(text) is None


class TestEvidenceShape:
    @patch("nfr_review.collectors.adr_derive.create_llm_client")
    def test_produces_derived_and_summary_evidence(
        self, mock_cls: MagicMock, tmp_path: Path
    ) -> None:
        mock_client = MagicMock()
        mock_client.available = True
        mock_client.analyze.return_value = _VALID_LLM_RESPONSE
        mock_cls.return_value = mock_client

        collector = AdrDeriveCollector()
        results = collector.collect(_make_repo(tmp_path), config=None)

        derived = [e for e in results if e.kind == "adr-derived"]
        summaries = [e for e in results if e.kind == "adr-derive-summary"]
        assert len(derived) == 3
        assert len(summaries) == 1

    @patch("nfr_review.collectors.adr_derive.create_llm_client")
    def test_derived_evidence_payload_keys(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        mock_client = MagicMock()
        mock_client.available = True
        mock_client.analyze.return_value = _VALID_LLM_RESPONSE
        mock_cls.return_value = mock_client

        collector = AdrDeriveCollector()
        results = collector.collect(_make_repo(tmp_path), config=None)

        derived = next(e for e in results if e.kind == "adr-derived")
        expected_keys = {"title", "rationale", "category", "confidence", "evidence_refs"}
        assert set(derived.payload.keys()) == expected_keys

    @patch("nfr_review.collectors.adr_derive.create_llm_client")
    def test_summary_evidence_payload_keys(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        mock_client = MagicMock()
        mock_client.available = True
        mock_client.analyze.return_value = _VALID_LLM_RESPONSE
        mock_cls.return_value = mock_client

        collector = AdrDeriveCollector()
        results = collector.collect(_make_repo(tmp_path), config=None)

        summary = next(e for e in results if e.kind == "adr-derive-summary")
        assert summary.payload["total_derived"] == 3
        assert "data" in summary.payload["categories"]
        assert "infrastructure" in summary.payload["categories"]
        assert "deployment" in summary.payload["categories"]
        assert isinstance(summary.payload["avg_confidence"], float)
        assert 0.0 <= summary.payload["avg_confidence"] <= 1.0

    @patch("nfr_review.collectors.adr_derive.create_llm_client")
    def test_collector_metadata_on_derived(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        mock_client = MagicMock()
        mock_client.available = True
        mock_client.analyze.return_value = _VALID_LLM_RESPONSE
        mock_cls.return_value = mock_client

        collector = AdrDeriveCollector()
        results = collector.collect(_make_repo(tmp_path), config=None)

        for ev in results:
            assert ev.collector_name == "adr-derive"
            assert ev.collector_version == "0.1.0"


class TestPromptConstruction:
    @patch("nfr_review.collectors.adr_derive.create_llm_client")
    def test_prompt_includes_repo_context(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        mock_client = MagicMock()
        mock_client.available = True
        mock_client.analyze.return_value = _VALID_LLM_RESPONSE
        mock_cls.return_value = mock_client

        repo = _make_repo(tmp_path)
        collector = AdrDeriveCollector()
        collector.collect(repo, config=None)

        mock_client.analyze.assert_called_once()
        call_kwargs = mock_client.analyze.call_args
        prompt = call_kwargs.kwargs.get("prompt") or call_kwargs[1].get("prompt", "")
        bundle = call_kwargs.kwargs.get("evidence_bundle") or call_kwargs[1].get(
            "evidence_bundle", ""
        )

        # Prompt should mention architecture decisions
        assert "architecture" in prompt.lower() or "ADR" in prompt

        # Bundle should contain info from the repo config files
        assert "requirements.txt" in bundle
        assert "Dockerfile" in bundle

    @patch("nfr_review.collectors.adr_derive.create_llm_client")
    def test_analyze_called_with_max_tokens_2048(
        self, mock_cls: MagicMock, tmp_path: Path
    ) -> None:
        mock_client = MagicMock()
        mock_client.available = True
        mock_client.analyze.return_value = _VALID_LLM_RESPONSE
        mock_cls.return_value = mock_client

        collector = AdrDeriveCollector()
        collector.collect(_make_repo(tmp_path), config=None)

        call_kwargs = mock_client.analyze.call_args
        max_tokens = call_kwargs.kwargs.get("max_tokens") or call_kwargs[1].get("max_tokens")
        assert max_tokens == 2048

    @patch("nfr_review.collectors.adr_derive.create_llm_client")
    def test_existing_adrs_included_in_bundle(
        self, mock_cls: MagicMock, tmp_path: Path
    ) -> None:
        mock_client = MagicMock()
        mock_client.available = True
        mock_client.analyze.return_value = _VALID_LLM_RESPONSE
        mock_cls.return_value = mock_client

        repo = _make_repo(tmp_path)
        adr_dir = repo / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        (adr_dir / "0001-use-flask.md").write_text("# Use Flask\n\n## Status\n\nAccepted\n")

        collector = AdrDeriveCollector()
        collector.collect(repo, config=None)

        call_kwargs = mock_client.analyze.call_args
        bundle = call_kwargs.kwargs.get("evidence_bundle") or call_kwargs[1].get(
            "evidence_bundle", ""
        )
        assert "0001-use-flask.md" in bundle


class TestGracefulDegradation:
    @patch("nfr_review.collectors.adr_derive.create_llm_client")
    def test_garbage_llm_response_returns_skip(
        self, mock_cls: MagicMock, tmp_path: Path
    ) -> None:
        mock_client = MagicMock()
        mock_client.available = True
        mock_client.analyze.return_value = "I don't understand the question. Beep boop."
        mock_cls.return_value = mock_client

        collector = AdrDeriveCollector()
        results = collector.collect(_make_repo(tmp_path), config=None)

        assert len(results) == 1
        assert results[0].kind == "adr-derive-skip"
        assert "parse" in results[0].payload["reason"].lower()

    @patch("nfr_review.collectors.adr_derive.create_llm_client")
    def test_llm_exception_returns_skip(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        mock_client = MagicMock()
        mock_client.available = True
        mock_client.analyze.side_effect = RuntimeError("API timeout")
        mock_cls.return_value = mock_client

        collector = AdrDeriveCollector()
        results = collector.collect(_make_repo(tmp_path), config=None)

        assert len(results) == 1
        assert results[0].kind == "adr-derive-skip"
        assert "API timeout" in results[0].payload["reason"]

    @patch("nfr_review.collectors.adr_derive.create_llm_client")
    def test_empty_json_array_returns_no_evidence(
        self, mock_cls: MagicMock, tmp_path: Path
    ) -> None:
        mock_client = MagicMock()
        mock_client.available = True
        mock_client.analyze.return_value = "[]"
        mock_cls.return_value = mock_client

        collector = AdrDeriveCollector()
        results = collector.collect(_make_repo(tmp_path), config=None)

        # Empty array parses fine but yields no derived evidence and no summary
        assert len(results) == 0
