"""Tests for PythonDepsCollector — registration, parsing, enrichment, degradation."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from nfr_review.collectors.python_deps import PythonDepsCollector
from nfr_review.registry import collector_registry

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "python-deps-sample-repo"


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
        assert "python-deps" in collector_registry

    def test_collector_name_and_version(self) -> None:
        collector = PythonDepsCollector()
        assert collector.name == "python-deps"
        assert collector.version == "0.1.0"


# ---------------------------------------------------------------------------
# Evidence shape
# ---------------------------------------------------------------------------


class TestEvidenceShape:
    @patch("nfr_review.collectors.python_deps.DepsDevClient")
    def test_evidence_kind_is_python_deps(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = PythonDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        assert len(evidences) == 1
        assert evidences[0].kind == "python-deps"

    @patch("nfr_review.collectors.python_deps.DepsDevClient")
    def test_payload_has_required_top_level_keys(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = PythonDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        payload = evidences[0].payload
        assert "dependencies" in payload
        assert "manifest_files_found" in payload
        assert "enrichment_errors" in payload

    @patch("nfr_review.collectors.python_deps.DepsDevClient")
    def test_each_dependency_has_required_keys(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = PythonDepsCollector()
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
# Manifest parsing
# ---------------------------------------------------------------------------


class TestRequirementsParsing:
    @patch("nfr_review.collectors.python_deps.DepsDevClient")
    def test_parses_requirements_txt_packages(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = PythonDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        req_names = [d["name"] for d in deps if d["source_file"] == "requirements.txt"]
        assert "requests" in req_names
        assert "flask" in req_names
        assert "pydantic" in req_names
        assert "click" in req_names

    @patch("nfr_review.collectors.python_deps.DepsDevClient")
    def test_parses_version_constraints(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = PythonDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        by_name = {d["name"]: d for d in deps}
        assert by_name["requests"]["declared_version"] == ">=2.28"
        assert by_name["flask"]["declared_version"] == "==2.3.0"
        assert by_name["click"]["declared_version"] == ""

    @patch("nfr_review.collectors.python_deps.DepsDevClient")
    def test_skips_malformed_lines_gracefully(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = PythonDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        names = [d["name"] for d in deps]
        assert "!!!not-a-package" not in names


class TestPyprojectParsing:
    @patch("nfr_review.collectors.python_deps.DepsDevClient")
    def test_parses_pyproject_dependencies(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = PythonDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        pyproject_names = [d["name"] for d in deps if d["source_file"] == "pyproject.toml"]
        assert "boto3" in pyproject_names
        assert "rich" in pyproject_names

    @patch("nfr_review.collectors.python_deps.DepsDevClient")
    def test_includes_optional_dependencies(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = PythonDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        pyproject_names = [d["name"] for d in deps if d["source_file"] == "pyproject.toml"]
        assert "pytest" in pyproject_names

    @patch("nfr_review.collectors.python_deps.DepsDevClient")
    def test_manifest_files_found_lists_both(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = PythonDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        found = evidences[0].payload["manifest_files_found"]
        assert "requirements.txt" in found
        assert "pyproject.toml" in found


# ---------------------------------------------------------------------------
# deps.dev enrichment
# ---------------------------------------------------------------------------


class TestEnrichment:
    @patch("nfr_review.collectors.python_deps.DepsDevClient")
    def test_enriches_with_latest_version(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = PythonDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        dep = evidences[0].payload["dependencies"][0]
        assert dep["latest_version"] == "9.9.9"
        assert dep["latest_release_date"] == "2025-01-01T00:00:00Z"
        assert dep["deps_dev_status"] == "ok"


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    @patch("nfr_review.collectors.python_deps.DepsDevClient")
    def test_produces_evidence_when_deps_dev_returns_none(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions.return_value = None
        collector = PythonDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        assert len(evidences) == 1
        deps = evidences[0].payload["dependencies"]
        assert len(deps) > 0
        for dep in deps:
            assert dep["latest_version"] is None
            assert dep["deps_dev_status"] == "error"

    @patch("nfr_review.collectors.python_deps.DepsDevClient")
    def test_enrichment_errors_populated_on_failure(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions.return_value = None
        collector = PythonDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        errors = evidences[0].payload["enrichment_errors"]
        assert len(errors) > 0
        assert all("error" in e for e in errors)

    @patch("nfr_review.collectors.python_deps.DepsDevClient")
    def test_partial_enrichment_failure(self, mock_cls: MagicMock) -> None:
        mapping = {
            "requests": _make_versions_response("2.31.0", "2023-05-22T00:00:00Z"),
            "flask": None,
        }
        mock_cls.return_value.get_package_versions = _mock_get_versions(mapping)
        collector = PythonDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        by_name = {d["name"]: d for d in deps}
        assert by_name["requests"]["deps_dev_status"] == "ok"
        assert by_name["requests"]["latest_version"] == "2.31.0"
        assert by_name["flask"]["deps_dev_status"] == "error"
        assert by_name["flask"]["latest_version"] is None

    @patch("nfr_review.collectors.python_deps.DepsDevClient")
    def test_empty_versions_list_yields_not_found(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions.return_value = {"versions": []}
        collector = PythonDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        for dep in evidences[0].payload["dependencies"]:
            assert dep["deps_dev_status"] == "not_found"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    @patch("nfr_review.collectors.python_deps.DepsDevClient")
    def test_empty_repo_returns_no_evidence(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        collector = PythonDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert evidences == []

    @patch("nfr_review.collectors.python_deps.DepsDevClient")
    def test_requirements_in_subdirectory(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        subdir = tmp_path / "requirements"
        subdir.mkdir()
        (subdir / "requirements.txt").write_text("numpy>=1.24\n")
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = PythonDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert len(evidences) == 1
        deps = evidences[0].payload["dependencies"]
        assert deps[0]["name"] == "numpy"
        assert "requirements/requirements.txt" in deps[0]["source_file"]
