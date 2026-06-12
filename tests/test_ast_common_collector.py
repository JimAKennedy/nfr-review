# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for shared AST collector infrastructure (collectors/ast_common.py)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from nfr_review.collectors.ast_common import (
    BaseASTCollector,
    find_nodes,
    make_parser,
    text,
)
from nfr_review.models import BasePayload

# ---------------------------------------------------------------------------
# make_parser()
# ---------------------------------------------------------------------------


def test_make_parser_valid_language() -> None:
    parser = make_parser("python")
    assert isinstance(parser, __import__("tree_sitter").Parser)


def test_make_parser_invalid_language() -> None:
    with pytest.raises(ValueError, match="Unsupported tree-sitter language"):
        make_parser("brainfuck")


def test_make_parser_grammar_not_installed() -> None:
    with patch("importlib.import_module", side_effect=ImportError("no module")):
        with pytest.raises(ImportError, match="no module"):
            make_parser("python")


# ---------------------------------------------------------------------------
# text() helper
# ---------------------------------------------------------------------------


def test_text_extracts_substring() -> None:
    source = b"hello world"
    parser = make_parser("python")
    # Parse a trivial Python expression so we get a real node.
    tree = parser.parse(source)
    root = tree.root_node
    result = text(root, source)
    assert result == "hello world"


def test_text_extracts_child_node() -> None:
    source = b"x = 42\n"
    parser = make_parser("python")
    tree = parser.parse(source)
    # The root's first child is an expression_statement or assignment.
    first = tree.root_node.children[0]
    result = text(first, source)
    assert "42" in result


# ---------------------------------------------------------------------------
# find_nodes()
# ---------------------------------------------------------------------------


def test_find_nodes_returns_matching_descendants() -> None:
    source = b"x = 1\ny = 2\n"
    parser = make_parser("python")
    tree = parser.parse(source)
    # integer nodes are typed "integer" in tree-sitter-python
    integers = find_nodes(tree.root_node, "integer")
    assert len(integers) == 2
    vals = [text(n, source) for n in integers]
    assert vals == ["1", "2"]


def test_find_nodes_returns_empty_when_no_match() -> None:
    source = b"x = 1\n"
    parser = make_parser("python")
    tree = parser.parse(source)
    classes = find_nodes(tree.root_node, "class_definition")
    assert classes == []


def test_find_nodes_finds_nested() -> None:
    source = b"def f():\n    return [1, 2, 3]\n"
    parser = make_parser("python")
    tree = parser.parse(source)
    integers = find_nodes(tree.root_node, "integer")
    assert len(integers) == 3


# ---------------------------------------------------------------------------
# Concrete test subclass of BaseASTCollector
# ---------------------------------------------------------------------------


class _TestCollector(BaseASTCollector):
    name = "test-collector"
    version = "0.0.1"
    language = "python"
    file_extensions = (".py",)
    evidence_kind = "test-ast-file"

    def _parse_file(self, source: bytes, rel_path: str) -> dict[str, Any]:
        return {"line_count": source.count(b"\n")}


class _TestPayloadCollector(BaseASTCollector):
    """Collector that returns a BasePayload subclass instead of a dict."""

    name = "payload-collector"
    version = "0.0.2"
    language = "python"
    file_extensions = (".py",)
    evidence_kind = "typed-payload"

    class Payload(BasePayload):
        line_count: int = 0

    def _parse_file(self, source: bytes, rel_path: str) -> BasePayload:
        return self.Payload(line_count=source.count(b"\n"))


class _ErrorCollector(BaseASTCollector):
    """Collector whose _parse_file always raises."""

    name = "error-collector"
    version = "0.0.1"
    language = "python"
    file_extensions = (".py",)
    evidence_kind = "error-file"

    def _parse_file(self, source: bytes, rel_path: str) -> dict[str, Any]:
        raise RuntimeError("parse boom")


# ---------------------------------------------------------------------------
# BaseASTCollector._get_parser()
# ---------------------------------------------------------------------------


def test_get_parser_returns_parser() -> None:
    c = _TestCollector()
    parser = c._get_parser()
    assert parser is not None


def test_get_parser_returns_none_when_import_fails() -> None:
    c = _TestCollector()
    with patch(
        "nfr_review.collectors.ast_common.make_parser",
        side_effect=ImportError("missing"),
    ):
        result = c._get_parser()
    assert result is None


# ---------------------------------------------------------------------------
# BaseASTCollector.collect() — file discovery
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    """Create a minimal repo structure with .py files."""
    (tmp_path / "app.py").write_text("x = 1\n")
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "utils.py").write_text("y = 2\n")
    # Hidden directory — should be skipped
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "hook.py").write_text("z = 3\n")
    # Non-matching extension
    (tmp_path / "readme.md").write_text("# hi\n")
    return tmp_path


class _SimpleConfig:
    exclude_paths: list[str] = []
    exclude_test_paths: bool = False


def test_collect_discovers_py_files(sample_repo: Path) -> None:
    c = _TestCollector()
    results = c.collect(sample_repo, config=_SimpleConfig())
    locators = {e.locator for e in results}
    assert "app.py" in locators
    assert Path("lib") / "utils.py" == Path(next(loc for loc in locators if "utils" in loc))


def test_collect_skips_hidden_dirs(sample_repo: Path) -> None:
    c = _TestCollector()
    results = c.collect(sample_repo, config=_SimpleConfig())
    locators = {e.locator for e in results}
    assert not any(".git" in loc for loc in locators)


def test_collect_skips_non_matching_extensions(sample_repo: Path) -> None:
    c = _TestCollector()
    results = c.collect(sample_repo, config=_SimpleConfig())
    locators = {e.locator for e in results}
    assert not any(loc.endswith(".md") for loc in locators)


def test_collect_evidence_fields(sample_repo: Path) -> None:
    c = _TestCollector()
    results = c.collect(sample_repo, config=_SimpleConfig())
    assert len(results) >= 1
    ev = results[0]
    assert ev.collector_name == "test-collector"
    assert ev.collector_version == "0.0.1"
    assert ev.kind == "test-ast-file"
    assert isinstance(ev.payload, dict)
    assert "line_count" in ev.payload
    # dict payload should get file_path injected
    assert "file_path" in ev.payload


def test_collect_with_basepayload(sample_repo: Path) -> None:
    c = _TestPayloadCollector()
    results = c.collect(sample_repo, config=_SimpleConfig())
    assert len(results) >= 1
    ev = results[0]
    assert isinstance(ev.payload, BasePayload)


# ---------------------------------------------------------------------------
# Exclude patterns
# ---------------------------------------------------------------------------


def test_collect_respects_exclude_patterns(sample_repo: Path) -> None:
    class _ExcludeConfig:
        exclude_paths = ["lib/*"]
        exclude_test_paths = False

    c = _TestCollector()
    results = c.collect(sample_repo, config=_ExcludeConfig())
    locators = {e.locator for e in results}
    assert not any("utils" in loc for loc in locators)
    assert "app.py" in locators


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_collect_handles_oserror(tmp_path: Path) -> None:
    (tmp_path / "good.py").write_text("a = 1\n")
    c = _TestCollector()
    # Patch read_bytes on the Path object to raise OSError for one file
    orig_read = Path.read_bytes

    def patched_read(self: Path) -> bytes:
        if self.name == "good.py":
            raise OSError("permission denied")
        return orig_read(self)

    with patch.object(Path, "read_bytes", patched_read):
        results = c.collect(tmp_path, config=_SimpleConfig())
    # File that raised OSError is silently skipped
    assert len(results) == 0


def test_collect_handles_parse_error(sample_repo: Path) -> None:
    c = _ErrorCollector()
    results = c.collect(sample_repo, config=_SimpleConfig())
    # All files trigger RuntimeError in _parse_file — all skipped
    assert len(results) == 0


def test_collect_returns_empty_when_parser_unavailable() -> None:
    c = _TestCollector()
    with patch(
        "nfr_review.collectors.ast_common.make_parser",
        side_effect=ImportError("nope"),
    ):
        results = c.collect(Path("/nonexistent"), config=_SimpleConfig())
    assert results == []


# ---------------------------------------------------------------------------
# Exclude test paths
# ---------------------------------------------------------------------------


def test_collect_skips_test_paths_by_default(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("a = 1\n")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_app.py").write_text("b = 2\n")

    class _DefaultConfig:
        exclude_paths: list[str] = []
        exclude_test_paths = True

    c = _TestCollector()
    results = c.collect(tmp_path, config=_DefaultConfig())
    locators = {e.locator for e in results}
    assert any("app.py" in loc for loc in locators)
    assert not any("test_app" in loc for loc in locators)
