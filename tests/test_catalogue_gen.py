# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for scripts/generate_catalogue.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

from generate_catalogue import (  # noqa: E402
    _build_html,
    _severity_sort_key,
    generate_catalogue,
    main,
)

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "rule_catalogue_sample.json"


@pytest.fixture()
def sample_rules() -> list[dict]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


class TestBuildHtml:
    def test_contains_table(self, sample_rules: list[dict]) -> None:
        html = _build_html(sample_rules)
        assert "<table" in html
        assert "</table>" in html

    def test_contains_all_rule_ids(self, sample_rules: list[dict]) -> None:
        html = _build_html(sample_rules)
        for rule in sample_rules:
            assert rule["id"] in html

    def test_severity_badges_present(self, sample_rules: list[dict]) -> None:
        html = _build_html(sample_rules)
        for sev in {"critical", "high", "medium", "low"}:
            assert f">{sev}</span>" in html

    def test_category_filter_options(self, sample_rules: list[dict]) -> None:
        html = _build_html(sample_rules)
        assert '<option value="security">security</option>' in html
        assert '<option value="maintainability">maintainability</option>' in html

    def test_html_is_self_contained(self, sample_rules: list[dict]) -> None:
        html = _build_html(sample_rules)
        assert "<!DOCTYPE html>" in html
        assert "<style>" in html
        assert "<script>" in html
        assert "http" not in html.split("<style>")[1].split("</style>")[0]

    def test_escapes_html_entities(self) -> None:
        rules = [
            {
                "id": "test-<xss>",
                "severity": "low",
                "category": "security",
                "tags": ["<script>"],
                "description": 'A "dangerous" <rule>',
                "compliance_refs": [],
            }
        ]
        html = _build_html(rules)
        assert "<xss>" not in html
        assert "&lt;xss&gt;" in html
        assert "&lt;script&gt;" in html

    def test_rule_count_in_subtitle(self, sample_rules: list[dict]) -> None:
        html = _build_html(sample_rules)
        assert f"{len(sample_rules)} rules" in html


class TestSeveritySortKey:
    def test_critical_before_low(self) -> None:
        critical = {"severity": "critical", "id": "z"}
        low = {"severity": "low", "id": "a"}
        assert _severity_sort_key(critical) < _severity_sort_key(low)

    def test_same_severity_sorts_by_id(self) -> None:
        a = {"severity": "high", "id": "aaa"}
        b = {"severity": "high", "id": "zzz"}
        assert _severity_sort_key(a) < _severity_sort_key(b)


class TestGenerateCatalogue:
    def test_writes_output_file(self, sample_rules: list[dict], tmp_path: Path) -> None:
        out = tmp_path / "catalogue.html"
        html = generate_catalogue(sample_rules, out)
        assert out.exists()
        assert out.read_text(encoding="utf-8") == html

    def test_creates_parent_dirs(self, sample_rules: list[dict], tmp_path: Path) -> None:
        out = tmp_path / "deep" / "nested" / "catalogue.html"
        generate_catalogue(sample_rules, out)
        assert out.exists()

    def test_returns_html_without_output(self, sample_rules: list[dict]) -> None:
        html = generate_catalogue(sample_rules)
        assert "<table" in html


class TestMain:
    def test_reads_from_input_file(self, tmp_path: Path) -> None:
        out = tmp_path / "out.html"
        main(["--input", str(_FIXTURE), "--output", str(out)])
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "<table" in content
        assert "apim-auth-policy-missing" in content

    def test_reads_from_stdin(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        out = tmp_path / "out.html"
        monkeypatch.setattr("sys.stdin", open(_FIXTURE, encoding="utf-8"))
        main(["--output", str(out)])
        assert out.exists()

    def test_writes_to_stdout(self, capsys: pytest.CaptureFixture[str]) -> None:
        main(["--input", str(_FIXTURE)])
        captured = capsys.readouterr()
        assert "<table" in captured.out

    def test_empty_rules(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.json"
        empty.write_text("[]", encoding="utf-8")
        out = tmp_path / "out.html"
        main(["--input", str(empty), "--output", str(out)])
        content = out.read_text(encoding="utf-8")
        assert "0 rules" in content
