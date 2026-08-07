"""Tests for RustDepsCollector — registration, Cargo.toml parsing, enrichment."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from nfr_review.collectors.rust_deps import RustDepsCollector
from nfr_review.registry import collector_registry

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "rust-deps-sample-repo"


def _make_versions_response(version: str, published_at: str) -> dict[str, Any]:
    return {"versions": [{"versionKey": {"version": version}, "publishedAt": published_at}]}


def _mock_get_versions(
    mapping: dict[str, dict[str, Any] | None] | None = None,
) -> MagicMock:
    default_response = _make_versions_response("9.9.9", "2025-01-01T00:00:00Z")
    mock = MagicMock()
    if mapping is None:
        mock.return_value = default_response
    else:
        mock.side_effect = lambda eco, name: mapping.get(name, default_response)
    return mock


class TestRegistration:
    def test_registered_in_collector_registry(self) -> None:
        assert "rust-deps" in collector_registry

    def test_collector_name_and_version(self) -> None:
        collector = RustDepsCollector()
        assert collector.name == "rust-deps"
        assert collector.version == "0.1.0"


class TestEvidenceShape:
    @patch("nfr_review.collectors.rust_deps.DepsDevClient")
    def test_evidence_kind_is_rust_deps(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = RustDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        assert len(evidences) == 1
        assert evidences[0].kind == "rust-deps"

    @patch("nfr_review.collectors.rust_deps.DepsDevClient")
    def test_payload_has_required_top_level_keys(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = RustDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        payload = evidences[0].payload
        assert "dependencies" in payload
        assert "manifest_files_found" in payload
        assert "enrichment_errors" in payload


class TestCargoTomlParsing:
    @patch("nfr_review.collectors.rust_deps.DepsDevClient")
    def test_parses_dependencies_and_dev_dependencies(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = RustDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        names = {d["name"] for d in evidences[0].payload["dependencies"]}
        assert "serde" in names
        assert "tokio" in names
        assert "tempfile" in names

    @patch("nfr_review.collectors.rust_deps.DepsDevClient")
    def test_string_and_table_form_both_parsed(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = RustDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        by_name = {d["name"]: d for d in evidences[0].payload["dependencies"]}
        assert by_name["serde"]["declared_version"] == "1.0"
        assert by_name["tokio"]["declared_version"] == "1.35"

    @patch("nfr_review.collectors.rust_deps.DepsDevClient")
    def test_path_only_dependency_skipped(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = RustDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        names = {d["name"] for d in evidences[0].payload["dependencies"]}
        assert "local-lib" not in names

    @patch("nfr_review.collectors.rust_deps.DepsDevClient")
    def test_manifest_files_found(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = RustDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        assert "Cargo.toml" in evidences[0].payload["manifest_files_found"]


class TestEnrichment:
    @patch("nfr_review.collectors.rust_deps.DepsDevClient")
    def test_enriches_with_latest_version(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = RustDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        dep = evidences[0].payload["dependencies"][0]
        assert dep["latest_version"] == "9.9.9"
        assert dep["deps_dev_status"] == "ok"

    @patch("nfr_review.collectors.rust_deps.DepsDevClient")
    def test_calls_deps_dev_with_cargo_ecosystem(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = RustDepsCollector()
        collector.collect(FIXTURE_DIR, None)
        calls = mock_cls.return_value.get_package_versions.call_args_list
        assert len(calls) > 0
        for call in calls:
            assert call[0][0] == "cargo"


class TestGracefulDegradation:
    @patch("nfr_review.collectors.rust_deps.DepsDevClient")
    def test_produces_evidence_when_deps_dev_returns_none(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions.return_value = None
        collector = RustDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        assert len(deps) > 0
        for dep in deps:
            assert dep["latest_version"] is None
            assert dep["deps_dev_status"] == "error"

    @patch("nfr_review.collectors.rust_deps.DepsDevClient")
    def test_empty_versions_list_yields_not_found(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions.return_value = {"versions": []}
        collector = RustDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        for dep in evidences[0].payload["dependencies"]:
            assert dep["deps_dev_status"] == "not_found"


class TestEdgeCases:
    @patch("nfr_review.collectors.rust_deps.DepsDevClient")
    def test_empty_repo_returns_no_evidence(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        collector = RustDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert evidences == []

    @patch("nfr_review.collectors.rust_deps.DepsDevClient")
    def test_cargo_toml_with_no_deps(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "x"\nversion = "0.1.0"\n')
        collector = RustDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert evidences == []

    @patch("nfr_review.collectors.rust_deps.DepsDevClient")
    def test_malformed_toml_skipped(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        (tmp_path / "Cargo.toml").write_text("this is not [ valid toml")
        collector = RustDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert evidences == []

    @patch("nfr_review.collectors.rust_deps.DepsDevClient")
    def test_nested_cargo_toml_in_workspace_member(
        self, mock_cls: MagicMock, tmp_path: Path
    ) -> None:
        member = tmp_path / "crates" / "core"
        member.mkdir(parents=True)
        (member / "Cargo.toml").write_text(
            '[package]\nname = "core"\nversion = "0.1.0"\n\n[dependencies]\nlog = "0.4"\n'
        )
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = RustDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert len(evidences) == 1
        deps = evidences[0].payload["dependencies"]
        assert deps[0]["name"] == "log"
        assert "crates/core/Cargo.toml" in deps[0]["source_file"]
