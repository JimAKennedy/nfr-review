"""A missing tree-sitter grammar (e.g. no aarch64 wheel for tree-sitter-dockerfile)
must surface as a visible run warning, not silently produce zero findings.

Deliberately does not depend on any real grammar being installed — every test
here mocks the grammar loader, so this exercises the same code path
regardless of which platform CI (or this environment) runs on.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from nfr_review.collectors.dockerfile import DockerfileCollector
from nfr_review.collectors.go_ast import GoAstCollector
from nfr_review.config import Config
from nfr_review.engine import Engine
from nfr_review.registry import Registry


class TestBaseASTCollectorRaises:
    """Covers every BaseASTCollector subclass generically (Java, Python, Go,
    Rust, C++, C#, Node, HCL) — GoAstCollector stands in as one concrete
    example of the shared base-class behavior."""

    def test_raises_with_informative_message(self, tmp_path: Path) -> None:
        collector = GoAstCollector()
        with patch(
            "nfr_review.collectors.ast_common.make_parser",
            side_effect=ImportError("no module named tree_sitter_go"),
        ):
            with pytest.raises(RuntimeError, match="not installed on this platform"):
                collector.collect(tmp_path, config=None)


class TestDockerfileCollectorRaises:
    """DockerfileCollector doesn't subclass BaseASTCollector (it needs custom
    filename matching, not extension-based globbing), so it duplicates —
    and must independently uphold — the same contract."""

    def test_raises_with_informative_message(self, tmp_path: Path) -> None:
        collector = DockerfileCollector()
        with patch(
            "nfr_review.collectors.dockerfile.make_parser",
            side_effect=ImportError("no module named tree_sitter_dockerfile"),
        ):
            with pytest.raises(RuntimeError, match="not installed on this platform"):
                collector.collect(tmp_path, config=None)


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

        assert len(result.warnings) == 1
        assert "dockerfile" in result.warnings[0]
        assert "not installed on this platform" in result.warnings[0]

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
