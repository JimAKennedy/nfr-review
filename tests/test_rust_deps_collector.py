"""Tests for RustDepsCollector — registration, Cargo.toml parsing, enrichment."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

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
        assert "crates/core/Cargo.toml" in deps[0]["source_file"].replace("\\", "/")


def _read_text_spy(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Path, Any]]:
    """Record (path, encoding) for every Path.read_text call."""
    seen: list[tuple[Path, Any]] = []
    original = Path.read_text

    def spy(self: Path, *args: Any, **kwargs: Any) -> str:
        seen.append((self, kwargs.get("encoding", args[0] if args else None)))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", spy)
    return seen


class TestCargoResolution:
    @patch("nfr_review.collectors.rust_deps.DepsDevClient")
    def test_workspace_inherited_dependency_resolves_from_root(
        self, mock_cls: MagicMock, tmp_path: Path
    ) -> None:
        (tmp_path / "Cargo.toml").write_text(
            '[workspace]\nmembers = ["crates/app"]\n\n'
            "[workspace.dependencies]\n"
            'serde = { version = "1.0.190", features = ["derive"] }\n'
            'json = { package = "serde_json", version = "1.0.108" }\n'
        )
        member = tmp_path / "crates" / "app"
        member.mkdir(parents=True)
        (member / "Cargo.toml").write_text(
            '[package]\nname = "app"\nversion = "0.1.0"\n\n'
            "[dependencies]\n"
            "serde = { workspace = true }\n"
            "json = { workspace = true }\n"
        )
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        evidences = RustDepsCollector().collect(tmp_path, None)
        by_name = {d["name"]: d for d in evidences[0].payload["dependencies"]}
        assert set(by_name) == {"serde", "serde_json"}
        assert by_name["serde"]["declared_version"] == "1.0.190"
        assert by_name["serde_json"]["declared_version"] == "1.0.108"
        assert by_name["serde"]["source_file"] == "crates/app/Cargo.toml"

    @patch("nfr_review.collectors.rust_deps.DepsDevClient")
    def test_target_cfg_dependency_tables_parsed(
        self, mock_cls: MagicMock, tmp_path: Path
    ) -> None:
        (tmp_path / "Cargo.toml").write_text(
            '[package]\nname = "x"\nversion = "0.1.0"\n\n'
            "[target.'cfg(unix)'.dependencies]\n"
            'nix = "0.27"\n\n'
            "[target.'cfg(windows)'.dev-dependencies]\n"
            'winapi = { version = "0.3" }\n'
        )
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        evidences = RustDepsCollector().collect(tmp_path, None)
        by_name = {d["name"]: d for d in evidences[0].payload["dependencies"]}
        assert by_name["nix"]["declared_version"] == "0.27"
        assert by_name["winapi"]["declared_version"] == "0.3"

    @patch("nfr_review.collectors.rust_deps.DepsDevClient")
    def test_package_rename_resolves_to_real_crate(
        self, mock_cls: MagicMock, tmp_path: Path
    ) -> None:
        (tmp_path / "Cargo.toml").write_text(
            '[package]\nname = "x"\nversion = "0.1.0"\n\n'
            "[dependencies]\n"
            'http1 = { package = "hyper", version = "0.14" }\n'
        )
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        evidences = RustDepsCollector().collect(tmp_path, None)
        names = [d["name"] for d in evidences[0].payload["dependencies"]]
        assert names == ["hyper"]
        looked_up = [
            c[0][1] for c in mock_cls.return_value.get_package_versions.call_args_list
        ]
        assert looked_up == ["hyper"]

    @patch("nfr_review.collectors.rust_deps.DepsDevClient")
    def test_target_dir_is_never_read(
        self, mock_cls: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "Cargo.toml").write_text(
            '[package]\nname = "x"\nversion = "0.1.0"\n\n[dependencies]\nlog = "0.4"\n'
        )
        decoy = tmp_path / "target" / "package" / "vendored-0.1.0"
        decoy.mkdir(parents=True)
        (decoy / "Cargo.toml").write_text(
            '[package]\nname = "vendored"\nversion = "0.1.0"\n\n'
            '[dependencies]\nbogus-crate = "1"\n'
        )
        seen = _read_text_spy(monkeypatch)
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        evidences = RustDepsCollector().collect(tmp_path, None)
        assert [d["name"] for d in evidences[0].payload["dependencies"]] == ["log"]
        assert evidences[0].payload["manifest_files_found"] == ["Cargo.toml"]
        read = [p.relative_to(tmp_path).parts for p, _ in seen]
        assert all("target" not in parts for parts in read)

    @patch("nfr_review.collectors.rust_deps.DepsDevClient")
    def test_manifest_read_as_utf8(
        self, mock_cls: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "Cargo.toml").write_text(
            '[package]\nname = "x"\nversion = "0.1.0"\ndescription = "café ✓"\n\n'
            '[dependencies]\nlog = "0.4"\n',
            encoding="utf-8",
        )
        seen = _read_text_spy(monkeypatch)
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        RustDepsCollector().collect(tmp_path, None)
        cargo_reads = [enc for p, enc in seen if p.name == "Cargo.toml"]
        assert cargo_reads == ["utf-8"]
