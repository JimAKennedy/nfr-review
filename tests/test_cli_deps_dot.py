"""CLI integration tests for the --dot flag on the deps command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from nfr_review.cli import cli

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "java-deps-sample-repo"


def _fake_versions(ecosystem: str, package_name: str) -> dict | None:
    return {
        "versions": [
            {
                "versionKey": {"version": "99.0.0"},
                "publishedAt": "2026-01-15T00:00:00Z",
            }
        ]
    }


def _fake_dep_graph(ecosystem: str, package: str, version: str) -> dict | None:
    return None


@patch(
    "nfr_review.deps_dev_client.DepsDevClient.get_dependency_graph",
    side_effect=_fake_dep_graph,
)
@patch(
    "nfr_review.deps_dev_client.DepsDevClient.get_package_versions",
    side_effect=_fake_versions,
)
class TestDotHappyPath:
    def test_dot_file_created_with_valid_digraph(
        self, _mock_versions, _mock_graph, tmp_path: Path
    ) -> None:
        dot_file = tmp_path / "deps.dot"
        result = CliRunner().invoke(cli, ["deps", str(FIXTURE_DIR), "--dot", str(dot_file)])
        assert result.exit_code == 0, result.output
        assert dot_file.exists()
        content = dot_file.read_text()
        assert content.startswith("digraph")
        assert "spring_core" in content or "spring-core" in content
        assert "guava" in content

    def test_dot_contains_expected_maven_packages(
        self, _mock_versions, _mock_graph, tmp_path: Path
    ) -> None:
        dot_file = tmp_path / "out.dot"
        result = CliRunner().invoke(cli, ["deps", str(FIXTURE_DIR), "--dot", str(dot_file)])
        assert result.exit_code == 0, result.output
        content = dot_file.read_text()
        for pkg in ("spring_core", "guava", "junit"):
            assert pkg in content, f"expected {pkg} in DOT output"

    def test_dot_stderr_confirms_write(
        self, _mock_versions, _mock_graph, tmp_path: Path
    ) -> None:
        dot_file = tmp_path / "g.dot"
        result = CliRunner().invoke(cli, ["deps", str(FIXTURE_DIR), "--dot", str(dot_file)])
        assert result.exit_code == 0, result.output
        assert "DOT graph written to" in result.output


@patch(
    "nfr_review.deps_dev_client.DepsDevClient.get_dependency_graph",
    side_effect=_fake_dep_graph,
)
@patch(
    "nfr_review.deps_dev_client.DepsDevClient.get_package_versions",
    side_effect=_fake_versions,
)
class TestDotWithNoTree:
    def test_dot_works_with_no_tree_flag(
        self, _mock_versions, _mock_graph, tmp_path: Path
    ) -> None:
        dot_file = tmp_path / "flat.dot"
        result = CliRunner().invoke(
            cli,
            ["deps", str(FIXTURE_DIR), "--no-tree", "--dot", str(dot_file)],
        )
        assert result.exit_code == 0, result.output
        assert dot_file.exists()
        content = dot_file.read_text()
        assert content.startswith("digraph")
        assert "guava" in content


class TestDotErrorCases:
    def test_nonexistent_target_exits_1(self, tmp_path: Path) -> None:
        dot_file = tmp_path / "nope.dot"
        fake_target = tmp_path / "no-such-dir"
        result = CliRunner().invoke(cli, ["deps", str(fake_target), "--dot", str(dot_file)])
        assert result.exit_code == 1
        assert "does not exist" in result.output
        assert not dot_file.exists()

    def test_target_is_file_rejected_by_click(self, tmp_path: Path) -> None:
        target_file = tmp_path / "afile.txt"
        target_file.write_text("hi")
        dot_file = tmp_path / "nope.dot"
        result = CliRunner().invoke(cli, ["deps", str(target_file), "--dot", str(dot_file)])
        assert result.exit_code == 2
        assert not dot_file.exists()
