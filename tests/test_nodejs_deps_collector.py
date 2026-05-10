"""Tests for NodejsDepsCollector — registration, parsing, enrichment, degradation."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from nfr_review.collectors.nodejs_deps import NodejsDepsCollector
from nfr_review.registry import collector_registry

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "nodejs-deps-sample-repo"


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
        assert "nodejs-deps" in collector_registry

    def test_collector_name_and_version(self) -> None:
        collector = NodejsDepsCollector()
        assert collector.name == "nodejs-deps"
        assert collector.version == "0.1.0"


# ---------------------------------------------------------------------------
# Evidence shape
# ---------------------------------------------------------------------------


class TestEvidenceShape:
    @patch("nfr_review.collectors.nodejs_deps.DepsDevClient")
    def test_evidence_kind_is_nodejs_deps(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = NodejsDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        assert len(evidences) == 1
        assert evidences[0].kind == "nodejs-deps"

    @patch("nfr_review.collectors.nodejs_deps.DepsDevClient")
    def test_payload_has_required_top_level_keys(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = NodejsDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        payload = evidences[0].payload
        assert "dependencies" in payload
        assert "manifest_files_found" in payload
        assert "enrichment_errors" in payload

    @patch("nfr_review.collectors.nodejs_deps.DepsDevClient")
    def test_each_dependency_has_required_keys(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = NodejsDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        required = {
            "name",
            "declared_version",
            "latest_version",
            "latest_release_date",
            "version_constraint",
            "deps_dev_status",
            "source_file",
        }
        for dep in evidences[0].payload["dependencies"]:
            assert required <= set(dep.keys()), (
                f"Missing keys in {dep['name']}: {required - set(dep.keys())}"
            )


# ---------------------------------------------------------------------------
# package.json parsing
# ---------------------------------------------------------------------------


class TestPackageJsonParsing:
    @patch("nfr_review.collectors.nodejs_deps.DepsDevClient")
    def test_parses_dependencies(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = NodejsDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        names = [d["name"] for d in deps]
        assert "express" in names
        assert "lodash" in names
        assert "axios" in names

    @patch("nfr_review.collectors.nodejs_deps.DepsDevClient")
    def test_parses_dev_dependencies(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = NodejsDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        names = [d["name"] for d in deps]
        assert "jest" in names

    @patch("nfr_review.collectors.nodejs_deps.DepsDevClient")
    def test_parses_peer_dependencies(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = NodejsDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        names = [d["name"] for d in deps]
        assert "react" in names

    @patch("nfr_review.collectors.nodejs_deps.DepsDevClient")
    def test_version_constraints_preserved(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = NodejsDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        by_name = {d["name"]: d for d in deps}
        assert by_name["express"]["declared_version"] == "^4.18.2"
        assert by_name["lodash"]["declared_version"] == "~4.17.21"
        assert by_name["jest"]["declared_version"] == "29.7.0"

    @patch("nfr_review.collectors.nodejs_deps.DepsDevClient")
    def test_scoped_packages_handled(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = NodejsDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        names = [d["name"] for d in deps]
        assert "@types/node" in names

    @patch("nfr_review.collectors.nodejs_deps.DepsDevClient")
    def test_manifest_files_found(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = NodejsDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        found = evidences[0].payload["manifest_files_found"]
        assert "package.json" in found


# ---------------------------------------------------------------------------
# Malformed inputs
# ---------------------------------------------------------------------------


class TestMalformedInputs:
    @patch("nfr_review.collectors.nodejs_deps.DepsDevClient")
    def test_missing_dependencies_field(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name": "bare", "version": "1.0.0"}')
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = NodejsDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert evidences == []

    @patch("nfr_review.collectors.nodejs_deps.DepsDevClient")
    def test_non_json_content(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text("this is not json at all")
        collector = NodejsDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert evidences == []

    @patch("nfr_review.collectors.nodejs_deps.DepsDevClient")
    def test_empty_file(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text("")
        collector = NodejsDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert evidences == []


# ---------------------------------------------------------------------------
# deps.dev enrichment
# ---------------------------------------------------------------------------


class TestEnrichment:
    @patch("nfr_review.collectors.nodejs_deps.DepsDevClient")
    def test_enriches_with_latest_version(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = NodejsDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        dep = evidences[0].payload["dependencies"][0]
        assert dep["latest_version"] == "9.9.9"
        assert dep["latest_release_date"] == "2025-01-01T00:00:00Z"
        assert dep["deps_dev_status"] == "ok"

    @patch("nfr_review.collectors.nodejs_deps.DepsDevClient")
    def test_calls_deps_dev_with_npm_ecosystem(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = NodejsDepsCollector()
        collector.collect(FIXTURE_DIR, None)
        calls = mock_cls.return_value.get_package_versions.call_args_list
        for call in calls:
            assert call[0][0] == "npm"


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    @patch("nfr_review.collectors.nodejs_deps.DepsDevClient")
    def test_produces_evidence_when_deps_dev_returns_none(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions.return_value = None
        collector = NodejsDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        assert len(evidences) == 1
        deps = evidences[0].payload["dependencies"]
        assert len(deps) > 0
        for dep in deps:
            assert dep["latest_version"] is None
            assert dep["deps_dev_status"] == "error"

    @patch("nfr_review.collectors.nodejs_deps.DepsDevClient")
    def test_enrichment_errors_populated_on_failure(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions.return_value = None
        collector = NodejsDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        errors = evidences[0].payload["enrichment_errors"]
        assert len(errors) > 0
        assert all("error" in e for e in errors)

    @patch("nfr_review.collectors.nodejs_deps.DepsDevClient")
    def test_partial_enrichment_failure(self, mock_cls: MagicMock) -> None:
        mapping = {
            "express": _make_versions_response("4.19.0", "2024-03-20T00:00:00Z"),
            "lodash": None,
        }
        mock_cls.return_value.get_package_versions = _mock_get_versions(mapping)
        collector = NodejsDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        by_name = {d["name"]: d for d in deps}
        assert by_name["express"]["deps_dev_status"] == "ok"
        assert by_name["express"]["latest_version"] == "4.19.0"
        assert by_name["lodash"]["deps_dev_status"] == "error"
        assert by_name["lodash"]["latest_version"] is None

    @patch("nfr_review.collectors.nodejs_deps.DepsDevClient")
    def test_empty_versions_list_yields_not_found(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions.return_value = {"versions": []}
        collector = NodejsDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        for dep in evidences[0].payload["dependencies"]:
            assert dep["deps_dev_status"] == "not_found"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    @patch("nfr_review.collectors.nodejs_deps.DepsDevClient")
    def test_empty_repo_returns_no_evidence(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        collector = NodejsDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert evidences == []

    @patch("nfr_review.collectors.nodejs_deps.DepsDevClient")
    def test_package_json_inside_node_modules_is_skipped(
        self, mock_cls: MagicMock, tmp_path: Path
    ) -> None:
        nm = tmp_path / "node_modules" / "express"
        nm.mkdir(parents=True)
        (nm / "package.json").write_text(
            '{"name": "express", "dependencies": {"accepts": "~1.3.8"}}'
        )
        collector = NodejsDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert evidences == []

    @patch("nfr_review.collectors.nodejs_deps.DepsDevClient")
    def test_nested_package_json_in_subdirectory(
        self, mock_cls: MagicMock, tmp_path: Path
    ) -> None:
        subdir = tmp_path / "packages" / "core"
        subdir.mkdir(parents=True)
        (subdir / "package.json").write_text(
            '{"name": "core", "dependencies": {"uuid": "^9.0.0"}}'
        )
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = NodejsDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert len(evidences) == 1
        deps = evidences[0].payload["dependencies"]
        assert deps[0]["name"] == "uuid"
        assert "packages/core/package.json" in deps[0]["source_file"]

    @patch("nfr_review.collectors.nodejs_deps.DepsDevClient")
    def test_empty_dependencies_object(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name": "bare", "dependencies": {}}')
        collector = NodejsDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert evidences == []
