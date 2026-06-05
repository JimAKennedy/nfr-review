# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for inline suppression marker parsing and filtering."""

from __future__ import annotations

from pathlib import Path

from nfr_review.models import Finding
from nfr_review.suppression import (
    SuppressionInfo,
    apply_suppressions,
    is_finding_suppressed,
    parse_suppression_marker,
)


def _make_finding(
    rule_id: str = "cpp-raw-memory",
    evidence_locator: str = "controller.cpp:10",
    **kwargs,
) -> Finding:
    defaults = {
        "rule_id": rule_id,
        "rag": "amber",
        "severity": "medium",
        "summary": "Test finding",
        "recommendation": "Fix it",
        "evidence_locator": evidence_locator,
        "collector_name": "test-collector",
        "collector_version": "0.1.0",
        "confidence": 0.9,
        "pattern_tag": "cpp-raw-new",
    }
    defaults.update(kwargs)
    return Finding(**defaults)


class TestParseSuppressionMarker:
    def test_cpp_single_rule(self) -> None:
        line = "auto* w = new CTextLabel(size);  // nfr-review:skip(cpp-raw-memory)"
        rule_ids, reason = parse_suppression_marker(line)
        assert rule_ids == {"cpp-raw-memory"}
        assert reason is None

    def test_python_hash_comment(self) -> None:
        line = "# nfr-review:skip(python-broad-except)"
        rule_ids, reason = parse_suppression_marker(line)
        assert rule_ids == {"python-broad-except"}
        assert reason is None

    def test_c_block_comment(self) -> None:
        line = "ptr = malloc(64); /* nfr-review:skip(cpp-raw-memory) */"
        rule_ids, reason = parse_suppression_marker(line)
        assert rule_ids == {"cpp-raw-memory"}
        assert reason is None

    def test_multiple_rules(self) -> None:
        line = "// nfr-review:skip(cpp-raw-memory, cpp-manual-delete)"
        rule_ids, reason = parse_suppression_marker(line)
        assert rule_ids == {"cpp-raw-memory", "cpp-manual-delete"}
        assert reason is None

    def test_wildcard(self) -> None:
        line = "// nfr-review:skip(*)"
        rule_ids, reason = parse_suppression_marker(line)
        assert rule_ids == {"*"}
        assert reason is None

    def test_no_marker(self) -> None:
        rule_ids, reason = parse_suppression_marker("auto* w = new CTextLabel(size);")
        assert rule_ids == set()
        assert reason is None

    def test_malformed_no_parens(self) -> None:
        rule_ids, reason = parse_suppression_marker("// nfr-review:skip")
        assert rule_ids == set()
        assert reason is None

    def test_empty_parens(self) -> None:
        rule_ids, reason = parse_suppression_marker("// nfr-review:skip()")
        assert rule_ids == set()
        assert reason is None

    def test_case_insensitive(self) -> None:
        line = "// NFR-Review:Skip(cpp-raw-memory)"
        rule_ids, reason = parse_suppression_marker(line)
        assert rule_ids == {"cpp-raw-memory"}
        assert reason is None

    def test_whitespace_in_rule_list(self) -> None:
        line = "// nfr-review:skip( cpp-raw-memory , cpp-manual-delete )"
        rule_ids, reason = parse_suppression_marker(line)
        assert rule_ids == {"cpp-raw-memory", "cpp-manual-delete"}
        assert reason is None

    # --- reason parsing ---

    def test_reason_cpp_line_comment(self) -> None:
        line = "// nfr-review:skip(cpp-raw-memory) reason: JIRA-1234 legacy allocation"
        rule_ids, reason = parse_suppression_marker(line)
        assert rule_ids == {"cpp-raw-memory"}
        assert reason == "JIRA-1234 legacy allocation"

    def test_reason_python_hash(self) -> None:
        line = "# nfr-review:skip(python-broad-except) reason: approved in review PR-99"
        rule_ids, reason = parse_suppression_marker(line)
        assert rule_ids == {"python-broad-except"}
        assert reason == "approved in review PR-99"

    def test_reason_c_block_comment(self) -> None:
        line = "/* nfr-review:skip(cpp-raw-memory) reason: VSTGUI requirement */"
        rule_ids, reason = parse_suppression_marker(line)
        assert rule_ids == {"cpp-raw-memory"}
        assert reason == "VSTGUI requirement"

    def test_reason_html_comment(self) -> None:
        line = "<!-- nfr-review:skip(k8s-resource-limits) reason: dev-only manifest -->"
        rule_ids, reason = parse_suppression_marker(line)
        assert rule_ids == {"k8s-resource-limits"}
        assert reason == "dev-only manifest"

    def test_reason_wildcard(self) -> None:
        line = "// nfr-review:skip(*) reason: entire file excluded"
        rule_ids, reason = parse_suppression_marker(line)
        assert rule_ids == {"*"}
        assert reason == "entire file excluded"

    def test_reason_multiple_rules(self) -> None:
        line = (
            "// nfr-review:skip(cpp-raw-memory, cpp-manual-delete) reason: RAII not available"
        )
        rule_ids, reason = parse_suppression_marker(line)
        assert rule_ids == {"cpp-raw-memory", "cpp-manual-delete"}
        assert reason == "RAII not available"

    def test_reason_case_insensitive_keyword(self) -> None:
        line = "// NFR-Review:Skip(rule-x) Reason: case test"
        rule_ids, reason = parse_suppression_marker(line)
        assert rule_ids == {"rule-x"}
        assert reason == "case test"

    def test_no_reason_returns_none(self) -> None:
        line = "// nfr-review:skip(cpp-raw-memory)"
        _, reason = parse_suppression_marker(line)
        assert reason is None


class TestIsFindingSuppressed:
    def test_same_line_marker(self, tmp_path: Path) -> None:
        src = tmp_path / "controller.cpp"
        src.write_text(
            "line1\nauto* w = new CTextLabel(s);  // nfr-review:skip(cpp-raw-memory)\nline3\n"
        )
        f = _make_finding(evidence_locator=f"{src}:2")
        cache: dict[str, list[str]] = {}
        info = is_finding_suppressed(f, cache)
        assert info is not None
        assert "cpp-raw-memory" in info.rule_ids
        assert info.reason is None

    def test_same_line_with_reason(self, tmp_path: Path) -> None:
        src = tmp_path / "controller.cpp"
        marker = "// nfr-review:skip(cpp-raw-memory) reason: JIRA-42"
        src.write_text(f"line1\nauto* w = new CTextLabel(s);  {marker}\nline3\n")
        f = _make_finding(evidence_locator=f"{src}:2")
        cache: dict[str, list[str]] = {}
        info = is_finding_suppressed(f, cache)
        assert info is not None
        assert info.reason == "JIRA-42"
        assert info.source_file == str(src)
        assert info.source_line == 2

    def test_line_above_marker(self, tmp_path: Path) -> None:
        src = tmp_path / "controller.cpp"
        src.write_text(
            "line1\n// nfr-review:skip(cpp-raw-memory)\nauto* w = new CTextLabel(s);\nline4\n"
        )
        f = _make_finding(evidence_locator=f"{src}:3")
        cache: dict[str, list[str]] = {}
        info = is_finding_suppressed(f, cache)
        assert info is not None
        assert info.source_line == 2

    def test_line_above_with_reason(self, tmp_path: Path) -> None:
        src = tmp_path / "controller.cpp"
        src.write_text(
            "line1\n"
            "// nfr-review:skip(cpp-raw-memory) reason: approved\n"
            "auto* w = new CTextLabel(s);\n"
            "line4\n"
        )
        f = _make_finding(evidence_locator=f"{src}:3")
        cache: dict[str, list[str]] = {}
        info = is_finding_suppressed(f, cache)
        assert info is not None
        assert info.reason == "approved"
        assert info.source_line == 2

    def test_no_marker_not_suppressed(self, tmp_path: Path) -> None:
        src = tmp_path / "controller.cpp"
        src.write_text("line1\nauto* w = new CTextLabel(s);\nline3\n")
        f = _make_finding(evidence_locator=f"{src}:2")
        cache: dict[str, list[str]] = {}
        assert is_finding_suppressed(f, cache) is None

    def test_wrong_rule_not_suppressed(self, tmp_path: Path) -> None:
        src = tmp_path / "controller.cpp"
        src.write_text(
            "line1\n"
            "auto* w = new CTextLabel(s);  // nfr-review:skip(cpp-manual-delete)\n"
            "line3\n"
        )
        f = _make_finding(
            rule_id="cpp-raw-memory",
            evidence_locator=f"{src}:2",
        )
        cache: dict[str, list[str]] = {}
        assert is_finding_suppressed(f, cache) is None

    def test_wildcard_suppresses_any_rule(self, tmp_path: Path) -> None:
        src = tmp_path / "code.py"
        src.write_text("# nfr-review:skip(*)\nexcept Exception:\n    pass\n")
        f = _make_finding(
            rule_id="python-broad-except",
            evidence_locator=f"{src}:2",
        )
        cache: dict[str, list[str]] = {}
        info = is_finding_suppressed(f, cache)
        assert info is not None
        assert "*" in info.rule_ids

    def test_project_wide_locator_not_suppressed(self) -> None:
        f = _make_finding(evidence_locator="project-wide")
        cache: dict[str, list[str]] = {}
        assert is_finding_suppressed(f, cache) is None

    def test_missing_file_not_suppressed(self) -> None:
        f = _make_finding(evidence_locator="/nonexistent/file.cpp:10")
        cache: dict[str, list[str]] = {}
        assert is_finding_suppressed(f, cache) is None

    def test_target_root_resolution(self, tmp_path: Path) -> None:
        src = tmp_path / "src" / "controller.cpp"
        src.parent.mkdir(parents=True)
        src.write_text("auto* w = new CTextLabel(s);  // nfr-review:skip(cpp-raw-memory)\n")
        f = _make_finding(evidence_locator="src/controller.cpp:1")
        cache: dict[str, list[str]] = {}
        info = is_finding_suppressed(f, cache, target_root=tmp_path)
        assert info is not None

    def test_source_cache_reused(self, tmp_path: Path) -> None:
        src = tmp_path / "a.cpp"
        src.write_text(
            "new Foo();  // nfr-review:skip(cpp-raw-memory)\n"
            "new Bar();  // nfr-review:skip(cpp-raw-memory)\n"
        )
        cache: dict[str, list[str]] = {}
        f1 = _make_finding(evidence_locator=f"{src}:1")
        f2 = _make_finding(evidence_locator=f"{src}:2")
        assert is_finding_suppressed(f1, cache) is not None
        assert is_finding_suppressed(f2, cache) is not None
        assert str(src) in cache


class TestApplySuppressions:
    def test_partitions_correctly(self, tmp_path: Path) -> None:
        src = tmp_path / "code.cpp"
        src.write_text(
            "new Foo();  // nfr-review:skip(cpp-raw-memory)\n"
            "// unrelated comment\n"
            "new Bar();\n"
        )
        f_suppressed = _make_finding(evidence_locator=f"{src}:1")
        f_active = _make_finding(evidence_locator=f"{src}:3")
        active, suppressed = apply_suppressions([f_suppressed, f_active])
        assert len(active) == 1
        assert len(suppressed) == 1
        assert active[0].evidence_locator == f"{src}:3"
        finding, info = suppressed[0]
        assert finding.evidence_locator == f"{src}:1"
        assert isinstance(info, SuppressionInfo)

    def test_suppressed_with_reason(self, tmp_path: Path) -> None:
        src = tmp_path / "code.cpp"
        src.write_text(
            "new Foo();  // nfr-review:skip(cpp-raw-memory) reason: ticket ABC-123\n"
        )
        f = _make_finding(evidence_locator=f"{src}:1")
        _, suppressed = apply_suppressions([f])
        assert len(suppressed) == 1
        finding, info = suppressed[0]
        assert info.reason == "ticket ABC-123"
        assert info.source_line == 1

    def test_suppressed_without_reason(self, tmp_path: Path) -> None:
        src = tmp_path / "code.cpp"
        src.write_text("new Foo();  // nfr-review:skip(cpp-raw-memory)\n")
        f = _make_finding(evidence_locator=f"{src}:1")
        _, suppressed = apply_suppressions([f])
        _, info = suppressed[0]
        assert info.reason is None

    def test_empty_input(self) -> None:
        active, suppressed = apply_suppressions([])
        assert active == []
        assert suppressed == []

    def test_all_suppressed(self, tmp_path: Path) -> None:
        src = tmp_path / "code.cpp"
        src.write_text("new Foo();  // nfr-review:skip(*)\n")
        f = _make_finding(evidence_locator=f"{src}:1")
        active, suppressed = apply_suppressions([f])
        assert len(active) == 0
        assert len(suppressed) == 1

    def test_none_suppressed(self, tmp_path: Path) -> None:
        src = tmp_path / "code.cpp"
        src.write_text("new Foo();\nnew Bar();\n")
        f1 = _make_finding(evidence_locator=f"{src}:1")
        f2 = _make_finding(evidence_locator=f"{src}:2")
        active, suppressed = apply_suppressions([f1, f2])
        assert len(active) == 2
        assert len(suppressed) == 0
