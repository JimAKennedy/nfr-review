"""A missing tree-sitter grammar (e.g. no aarch64 wheel for tree-sitter-dockerfile)
must surface as a visible run warning, not silently produce zero findings.

Deliberately does not depend on any real grammar being installed — every test
here mocks the grammar loader, so this exercises the same code path
regardless of which platform CI (or this environment) runs on.

The one exception is the Go grammar, a core dependency installed
everywhere, which the parser-constructor case needs to reach
``tree_sitter.Parser``.
"""

from __future__ import annotations

import types
from pathlib import Path
from unittest.mock import patch

import pytest
import tree_sitter
import tree_sitter_go

from nfr_review.collectors.dockerfile import DockerfileCollector
from nfr_review.collectors.go_ast import GoAstCollector
from nfr_review.config import Config
from nfr_review.engine import Engine
from nfr_review.registry import Registry

_GO_WARNING = "tree-sitter grammar for go not installed on this platform — collector disabled"
_DOCKERFILE_WARNING = (
    "tree-sitter grammar for dockerfile not installed on this platform — collector disabled"
)


def _placeholder_grammar_module() -> types.ModuleType:
    """A grammar package with no language function, like the 0.0.0a1 placeholder."""
    return types.ModuleType("tree_sitter_placeholder")


def _raise_attribute_error() -> object:
    raise AttributeError("bug inside the grammar's language()")


def _buggy_grammar_module() -> types.ModuleType:
    """A grammar package whose language function itself raises AttributeError."""
    mod = types.ModuleType("tree_sitter_buggy")
    mod.language = _raise_attribute_error  # type: ignore[attr-defined]
    return mod


def _go_backed_grammar_module() -> types.ModuleType:
    """A grammar package that loads fine (backed by the installed Go grammar)."""
    mod = types.ModuleType("tree_sitter_stand_in")
    mod.language = tree_sitter_go.language  # type: ignore[attr-defined]
    return mod


class TestMakeParser:
    def test_missing_language_function_raises_grammar_not_installed(self) -> None:
        from nfr_review.collectors.ast_common import GrammarNotInstalledError, make_parser

        with patch("importlib.import_module", return_value=_placeholder_grammar_module()):
            with pytest.raises(GrammarNotInstalledError, match="does not provide language"):
                make_parser("dockerfile")

    def test_grammar_not_installed_is_an_import_error(self) -> None:
        from nfr_review.collectors.ast_common import GrammarNotInstalledError

        assert issubclass(GrammarNotInstalledError, ImportError)

    def test_attribute_error_inside_language_function_propagates(self) -> None:
        from nfr_review.collectors.ast_common import GrammarNotInstalledError, make_parser

        with patch("importlib.import_module", return_value=_buggy_grammar_module()):
            with pytest.raises(AttributeError, match="bug inside") as excinfo:
                make_parser("dockerfile")
        assert not isinstance(excinfo.value, GrammarNotInstalledError)


class TestBaseASTCollectorRecordsWarning:
    """Covers every BaseASTCollector subclass generically (Java, Python, Go,
    Rust, C++, C#, Node, HCL) — GoAstCollector stands in as one concrete
    example of the shared base-class behavior."""

    def test_missing_module_records_warning(self, tmp_path: Path) -> None:
        collector = GoAstCollector()
        with patch(
            "nfr_review.collectors.ast_common.make_parser",
            side_effect=ImportError("no module named tree_sitter_go"),
        ):
            result = collector.collect(tmp_path, config=None)
        assert result == []
        assert collector.grammar_warnings == [_GO_WARNING]

    def test_missing_language_function_records_warning(self, tmp_path: Path) -> None:
        collector = GoAstCollector()
        with patch("importlib.import_module", return_value=_placeholder_grammar_module()):
            result = collector.collect(tmp_path, config=None)
        assert result == []
        assert collector.grammar_warnings == [_GO_WARNING]

    def test_attribute_error_inside_language_function_propagates(self, tmp_path: Path) -> None:
        collector = GoAstCollector()
        with patch("importlib.import_module", return_value=_buggy_grammar_module()):
            with pytest.raises(AttributeError, match="bug inside"):
                collector.collect(tmp_path, config=None)
        assert collector.grammar_warnings == []

    def test_attribute_error_from_parser_constructor_propagates(self, tmp_path: Path) -> None:
        collector = GoAstCollector()
        with patch.object(
            tree_sitter, "Parser", side_effect=AttributeError("parser ctor bug")
        ):
            with pytest.raises(AttributeError, match="parser ctor bug"):
                collector.collect(tmp_path, config=None)
        assert collector.grammar_warnings == []

    def test_repeated_collect_records_the_warning_once(self, tmp_path: Path) -> None:
        collector = GoAstCollector()
        with patch(
            "nfr_review.collectors.ast_common.make_parser",
            side_effect=ImportError("no module named tree_sitter_go"),
        ):
            collector.collect(tmp_path, config=None)
            collector.collect(tmp_path, config=None)
        assert collector.grammar_warnings == [_GO_WARNING]

    def test_repeated_get_parser_records_the_warning_once(self) -> None:
        collector = GoAstCollector()
        with patch(
            "nfr_review.collectors.ast_common.make_parser",
            side_effect=ImportError("no module named tree_sitter_go"),
        ):
            assert collector._get_parser() is None
            assert collector._get_parser() is None
        assert collector.grammar_warnings == [_GO_WARNING]


class TestDockerfileCollectorRecordsWarning:
    """DockerfileCollector doesn't subclass BaseASTCollector (it needs custom
    filename matching, not extension-based globbing), so it duplicates —
    and must independently uphold — the same contract."""

    def test_missing_module_records_warning(self, tmp_path: Path) -> None:
        collector = DockerfileCollector()
        with patch(
            "nfr_review.collectors.dockerfile.make_parser",
            side_effect=ImportError("no module named tree_sitter_dockerfile"),
        ):
            result = collector.collect(tmp_path, config=None)
        assert result == []
        assert collector.grammar_warnings == [_DOCKERFILE_WARNING]

    def test_missing_language_function_records_warning(self, tmp_path: Path) -> None:
        collector = DockerfileCollector()
        with patch("importlib.import_module", return_value=_placeholder_grammar_module()):
            result = collector.collect(tmp_path, config=None)
        assert result == []
        assert collector.grammar_warnings == [_DOCKERFILE_WARNING]

    def test_attribute_error_inside_language_function_propagates(self, tmp_path: Path) -> None:
        collector = DockerfileCollector()
        with patch("importlib.import_module", return_value=_buggy_grammar_module()):
            with pytest.raises(AttributeError, match="bug inside"):
                collector.collect(tmp_path, config=None)
        assert collector.grammar_warnings == []

    def test_attribute_error_from_parser_constructor_propagates(self, tmp_path: Path) -> None:
        collector = DockerfileCollector()
        with (
            patch("importlib.import_module", return_value=_go_backed_grammar_module()),
            patch.object(tree_sitter, "Parser", side_effect=AttributeError("parser ctor bug")),
        ):
            with pytest.raises(AttributeError, match="parser ctor bug"):
                collector.collect(tmp_path, config=None)
        assert collector.grammar_warnings == []

    def test_repeated_collect_records_the_warning_once(self, tmp_path: Path) -> None:
        collector = DockerfileCollector()
        with patch(
            "nfr_review.collectors.dockerfile.make_parser",
            side_effect=ImportError("no module named tree_sitter_dockerfile"),
        ):
            collector.collect(tmp_path, config=None)
            collector.collect(tmp_path, config=None)
        assert collector.grammar_warnings == [_DOCKERFILE_WARNING]


class TestEngineSurfacesTheWarning:
    """The actual point: does this reach RunResult.warnings, which the CLI
    prints unconditionally (not just under -v)?"""

    def test_missing_grammar_becomes_a_run_warning(self, tmp_path: Path) -> None:
        cregistry: Registry = Registry("collector")
        rregistry: Registry = Registry("rule")
        cregistry.register("dockerfile", DockerfileCollector())

        with patch(
            "nfr_review.collectors.dockerfile.make_parser",
            side_effect=ImportError("no module named tree_sitter_dockerfile"),
        ):
            engine = Engine(collectors=cregistry, rules=rregistry)
            result = engine.run(target=tmp_path, config=Config(tech={}))

        assert result.warnings == [_DOCKERFILE_WARNING]

    def test_run_does_not_abort_despite_the_failure(self, tmp_path: Path) -> None:
        """R012: a collector failure — even a categorical one like a missing
        grammar — must never abort the run."""
        cregistry: Registry = Registry("collector")
        rregistry: Registry = Registry("rule")
        cregistry.register("dockerfile", DockerfileCollector())

        with patch(
            "nfr_review.collectors.dockerfile.make_parser",
            side_effect=ImportError("no module named tree_sitter_dockerfile"),
        ):
            engine = Engine(collectors=cregistry, rules=rregistry)
            result = engine.run(target=tmp_path, config=Config(tech={}))

        assert result.findings == []
        assert result.run_metadata is not None

    @pytest.mark.parametrize("workers", [1, 4])
    def test_repeated_runs_report_the_warning_once_per_run(
        self, tmp_path: Path, workers: int
    ) -> None:
        """The registered collectors are module-level singletons reused by
        every run in the process, so the second run must not repeat the
        first run's warning."""
        cregistry: Registry = Registry("collector")
        rregistry: Registry = Registry("rule")
        cregistry.register("dockerfile", DockerfileCollector())
        cregistry.register("go-ast", GoAstCollector())

        with (
            patch(
                "nfr_review.collectors.dockerfile.make_parser",
                side_effect=ImportError("no module named tree_sitter_dockerfile"),
            ),
            patch(
                "nfr_review.collectors.ast_common.make_parser",
                side_effect=ImportError("no module named tree_sitter_go"),
            ),
        ):
            engine = Engine(collectors=cregistry, rules=rregistry, workers=workers)
            first = engine.run(target=tmp_path, config=Config(tech={}))
            second = engine.run(target=tmp_path, config=Config(tech={}))

        assert sorted(first.warnings) == sorted([_DOCKERFILE_WARNING, _GO_WARNING])
        assert sorted(second.warnings) == sorted([_DOCKERFILE_WARNING, _GO_WARNING])
