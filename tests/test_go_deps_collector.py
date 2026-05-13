"""Tests for GoDepsCollector — registration, parsing, enrichment, degradation."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from nfr_review.collectors.go_deps import GoDepsCollector
from nfr_review.registry import collector_registry

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "go-deps-sample-repo"


def _make_versions_response(version: str, published_at: str) -> dict[str, Any]:
    return {
        "versions": [
            {
                "versionKey": {"version": version},
                "publishedAt": published_at,
            }
        ]
    }


def _mock_get_versions(
    mapping: dict[str, dict[str, Any] | None] | None = None,
) -> MagicMock:
    """Return a mock DepsDevClient.get_package_versions with per-package responses."""
    default_response = _make_versions_response("9.9.9", "2025-01-01T00:00:00Z")
    mock = MagicMock()
    if mapping is None:
        mock.return_value = default_response
    else:
        mock.side_effect = lambda eco, name: mapping.get(name, default_response)
    return mock


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_registered_in_collector_registry(self) -> None:
        assert "go-deps" in collector_registry

    def test_collector_name_and_version(self) -> None:
        collector = GoDepsCollector()
        assert collector.name == "go-deps"
        assert collector.version == "0.1.0"


# ---------------------------------------------------------------------------
# Evidence shape
# ---------------------------------------------------------------------------


class TestEvidenceShape:
    @patch("nfr_review.collectors.go_deps.DepsDevClient")
    def test_evidence_kind_is_go_deps(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = GoDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        assert len(evidences) == 1
        assert evidences[0].kind == "go-deps"

    @patch("nfr_review.collectors.go_deps.DepsDevClient")
    def test_payload_has_required_top_level_keys(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = GoDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        payload = evidences[0].payload
        assert "dependencies" in payload
        assert "manifest_files_found" in payload
        assert "enrichment_errors" in payload

    @patch("nfr_review.collectors.go_deps.DepsDevClient")
    def test_each_dependency_has_required_keys(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = GoDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        required = {
            "name",
            "declared_version",
            "latest_version",
            "latest_release_date",
            "version_constraint",
            "deps_dev_status",
            "source_file",
            "indirect",
        }
        for dep in evidences[0].payload["dependencies"]:
            assert required <= set(dep.keys()), (
                f"Missing keys in {dep['name']}: {required - set(dep.keys())}"
            )


# ---------------------------------------------------------------------------
# go.mod parsing
# ---------------------------------------------------------------------------


class TestGoModParsing:
    @patch("nfr_review.collectors.go_deps.DepsDevClient")
    def test_parses_require_block(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = GoDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        names = [d["name"] for d in deps]
        assert "github.com/gin-gonic/gin" in names
        assert "golang.org/x/net" in names
        assert "github.com/stretchr/testify" in names

    @patch("nfr_review.collectors.go_deps.DepsDevClient")
    def test_parses_single_line_require(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = GoDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        names = [d["name"] for d in deps]
        assert "github.com/google/uuid" in names

    @patch("nfr_review.collectors.go_deps.DepsDevClient")
    def test_detects_indirect_dependencies(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = GoDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        by_name = {d["name"]: d for d in deps}
        assert by_name["golang.org/x/net"]["indirect"] is True
        assert by_name["github.com/gin-gonic/gin"]["indirect"] is False

    @patch("nfr_review.collectors.go_deps.DepsDevClient")
    def test_skips_replace_directives(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = GoDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        names = [d["name"] for d in deps]
        assert "github.com/old/module" not in names
        assert "github.com/new/module" not in names

    @patch("nfr_review.collectors.go_deps.DepsDevClient")
    def test_correct_version_strings(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = GoDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        by_name = {d["name"]: d for d in deps}
        assert by_name["github.com/gin-gonic/gin"]["declared_version"] == "v1.9.1"
        assert by_name["golang.org/x/net"]["declared_version"] == "v0.17.0"
        assert by_name["github.com/google/uuid"]["declared_version"] == "v1.4.0"

    @patch("nfr_review.collectors.go_deps.DepsDevClient")
    def test_version_constraint_normalized_to_pep440(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = GoDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        by_name = {d["name"]: d for d in deps}
        assert by_name["github.com/gin-gonic/gin"]["version_constraint"] == "1.9.1"
        assert by_name["golang.org/x/net"]["version_constraint"] == "0.17.0"
        assert by_name["github.com/google/uuid"]["version_constraint"] == "1.4.0"

    @patch("nfr_review.collectors.go_deps.DepsDevClient")
    def test_manifest_files_found(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = GoDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        found = evidences[0].payload["manifest_files_found"]
        assert "go.mod" in found

    @patch("nfr_review.collectors.go_deps.DepsDevClient")
    def test_skips_exclude_block(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text(
            "module example.com/app\n\ngo 1.21\n\n"
            "require github.com/real/dep v1.0.0\n\n"
            "exclude (\n\tgithub.com/bad/dep v0.1.0\n)\n"
        )
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = GoDepsCollector()
        evidences = collector.collect(tmp_path, None)
        deps = evidences[0].payload["dependencies"]
        names = [d["name"] for d in deps]
        assert "github.com/real/dep" in names
        assert "github.com/bad/dep" not in names

    @patch("nfr_review.collectors.go_deps.DepsDevClient")
    def test_skips_retract_directive(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text(
            "module example.com/app\n\ngo 1.21\n\n"
            "require github.com/dep/a v2.0.0\n\n"
            "retract v1.0.0\n"
        )
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = GoDepsCollector()
        evidences = collector.collect(tmp_path, None)
        deps = evidences[0].payload["dependencies"]
        assert len(deps) == 1
        assert deps[0]["name"] == "github.com/dep/a"


# ---------------------------------------------------------------------------
# deps.dev enrichment
# ---------------------------------------------------------------------------


class TestEnrichment:
    @patch("nfr_review.collectors.go_deps.DepsDevClient")
    def test_enriches_with_latest_version(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = GoDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        dep = evidences[0].payload["dependencies"][0]
        assert dep["latest_version"] == "9.9.9"
        assert dep["latest_release_date"] == "2025-01-01T00:00:00Z"
        assert dep["deps_dev_status"] == "ok"

    @patch("nfr_review.collectors.go_deps.DepsDevClient")
    def test_calls_deps_dev_with_go_ecosystem(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = GoDepsCollector()
        collector.collect(FIXTURE_DIR, None)
        calls = mock_cls.return_value.get_package_versions.call_args_list
        for call in calls:
            assert call[0][0] == "go"

    @patch("nfr_review.collectors.go_deps.DepsDevClient")
    def test_module_path_used_as_package_name(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = GoDepsCollector()
        collector.collect(FIXTURE_DIR, None)
        calls = mock_cls.return_value.get_package_versions.call_args_list
        package_names = [call[0][1] for call in calls]
        assert "github.com/gin-gonic/gin" in package_names
        assert "github.com/google/uuid" in package_names


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    @patch("nfr_review.collectors.go_deps.DepsDevClient")
    def test_produces_evidence_when_deps_dev_returns_none(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions.return_value = None
        collector = GoDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        assert len(evidences) == 1
        deps = evidences[0].payload["dependencies"]
        assert len(deps) > 0
        for dep in deps:
            assert dep["latest_version"] is None
            assert dep["deps_dev_status"] == "error"

    @patch("nfr_review.collectors.go_deps.DepsDevClient")
    def test_enrichment_errors_populated_on_failure(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions.return_value = None
        collector = GoDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        errors = evidences[0].payload["enrichment_errors"]
        assert len(errors) > 0
        assert all("error" in e for e in errors)

    @patch("nfr_review.collectors.go_deps.DepsDevClient")
    def test_partial_enrichment_failure(self, mock_cls: MagicMock) -> None:
        gin_resp = _make_versions_response("1.10.0", "2024-06-01T00:00:00Z")
        mapping = {
            "github.com/gin-gonic/gin": gin_resp,
            "golang.org/x/net": None,
        }
        mock_cls.return_value.get_package_versions = _mock_get_versions(mapping)
        collector = GoDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        by_name = {d["name"]: d for d in deps}
        assert by_name["github.com/gin-gonic/gin"]["deps_dev_status"] == "ok"
        assert by_name["github.com/gin-gonic/gin"]["latest_version"] == "1.10.0"
        assert by_name["golang.org/x/net"]["deps_dev_status"] == "error"
        assert by_name["golang.org/x/net"]["latest_version"] is None

    @patch("nfr_review.collectors.go_deps.DepsDevClient")
    def test_empty_versions_list_yields_not_found(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions.return_value = {"versions": []}
        collector = GoDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        for dep in evidences[0].payload["dependencies"]:
            assert dep["deps_dev_status"] == "not_found"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    @patch("nfr_review.collectors.go_deps.DepsDevClient")
    def test_empty_repo_returns_no_evidence(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        collector = GoDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert evidences == []

    @patch("nfr_review.collectors.go_deps.DepsDevClient")
    def test_go_mod_with_no_requires(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("module example.com/app\n\ngo 1.21\n")
        collector = GoDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert evidences == []

    @patch("nfr_review.collectors.go_deps.DepsDevClient")
    def test_nested_go_mod_in_subdirectory(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        subdir = tmp_path / "cmd" / "server"
        subdir.mkdir(parents=True)
        (subdir / "go.mod").write_text(
            "module example.com/server\n\ngo 1.21\n\nrequire github.com/lib/pq v1.10.9\n"
        )
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = GoDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert len(evidences) == 1
        deps = evidences[0].payload["dependencies"]
        assert deps[0]["name"] == "github.com/lib/pq"
        assert "cmd/server/go.mod" in deps[0]["source_file"]

    @patch("nfr_review.collectors.go_deps.DepsDevClient")
    def test_empty_go_mod_file(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("")
        collector = GoDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert evidences == []

    @patch("nfr_review.collectors.go_deps.DepsDevClient")
    def test_malformed_require_lines_skipped(
        self, mock_cls: MagicMock, tmp_path: Path
    ) -> None:
        (tmp_path / "go.mod").write_text(
            "module example.com/app\n\ngo 1.21\n\n"
            "require (\n"
            "\tgithub.com/good/dep v1.0.0\n"
            "\tthis-is-not-valid\n"
            "\tgithub.com/another/dep v2.0.0\n"
            ")\n"
        )
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = GoDepsCollector()
        evidences = collector.collect(tmp_path, None)
        deps = evidences[0].payload["dependencies"]
        names = [d["name"] for d in deps]
        assert "github.com/good/dep" in names
        assert "github.com/another/dep" in names
        assert len(deps) == 2

    @patch("nfr_review.collectors.go_deps.DepsDevClient")
    def test_missing_module_line(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("require github.com/some/dep v1.0.0\n")
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = GoDepsCollector()
        evidences = collector.collect(tmp_path, None)
        deps = evidences[0].payload["dependencies"]
        assert len(deps) == 1
        assert deps[0]["name"] == "github.com/some/dep"

    @patch("nfr_review.collectors.go_deps.DepsDevClient")
    def test_replace_block_skipped(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text(
            "module example.com/app\n\ngo 1.21\n\n"
            "require github.com/real/dep v1.0.0\n\n"
            "replace (\n"
            "\tgithub.com/old/dep => github.com/new/dep v2.0.0\n"
            ")\n"
        )
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = GoDepsCollector()
        evidences = collector.collect(tmp_path, None)
        deps = evidences[0].payload["dependencies"]
        names = [d["name"] for d in deps]
        assert "github.com/real/dep" in names
        assert "github.com/old/dep" not in names
        assert "github.com/new/dep" not in names
