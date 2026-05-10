"""Tests for CsharpDepsCollector — registration, parsing, enrichment, degradation."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from nfr_review.collectors.csharp_deps import CsharpDepsCollector
from nfr_review.registry import collector_registry

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "csharp-deps-sample-repo"


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
        assert "csharp-deps" in collector_registry

    def test_collector_name_and_version(self) -> None:
        collector = CsharpDepsCollector()
        assert collector.name == "csharp-deps"
        assert collector.version == "0.1.0"


# ---------------------------------------------------------------------------
# Evidence shape
# ---------------------------------------------------------------------------


class TestEvidenceShape:
    @patch("nfr_review.collectors.csharp_deps.DepsDevClient")
    def test_evidence_kind_is_csharp_deps(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = CsharpDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        assert len(evidences) == 1
        assert evidences[0].kind == "csharp-deps"

    @patch("nfr_review.collectors.csharp_deps.DepsDevClient")
    def test_payload_has_required_top_level_keys(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = CsharpDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        payload = evidences[0].payload
        assert "dependencies" in payload
        assert "manifest_files_found" in payload
        assert "enrichment_errors" in payload

    @patch("nfr_review.collectors.csharp_deps.DepsDevClient")
    def test_each_dependency_has_required_keys(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = CsharpDepsCollector()
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
# .csproj parsing
# ---------------------------------------------------------------------------


class TestCsprojParsing:
    @patch("nfr_review.collectors.csharp_deps.DepsDevClient")
    def test_parses_package_references(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = CsharpDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        names = [d["name"] for d in deps]
        assert "Newtonsoft.Json" in names
        assert "Serilog" in names
        assert "Microsoft.Extensions.Logging" in names
        assert "xunit" in names

    @patch("nfr_review.collectors.csharp_deps.DepsDevClient")
    def test_parses_version_attribute(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = CsharpDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        by_name = {d["name"]: d for d in deps}
        assert by_name["Newtonsoft.Json"]["declared_version"] == "13.0.3"
        assert by_name["Serilog"]["declared_version"] == "3.1.1"

    @patch("nfr_review.collectors.csharp_deps.DepsDevClient")
    def test_handles_multiple_item_groups(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = CsharpDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        names = [d["name"] for d in deps]
        assert "BenchmarkDotNet" in names
        assert len(deps) == 5

    @patch("nfr_review.collectors.csharp_deps.DepsDevClient")
    def test_handles_conditional_item_groups(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = CsharpDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        by_name = {d["name"]: d for d in deps}
        assert by_name["BenchmarkDotNet"]["declared_version"] == "0.13.10"

    @patch("nfr_review.collectors.csharp_deps.DepsDevClient")
    def test_version_as_child_element(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        csproj = tmp_path / "ChildVersion.csproj"
        csproj.write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            "  <ItemGroup>\n"
            '    <PackageReference Include="FluentValidation">\n'
            "      <Version>11.8.0</Version>\n"
            "    </PackageReference>\n"
            "  </ItemGroup>\n"
            "</Project>\n"
        )
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = CsharpDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert len(evidences) == 1
        deps = evidences[0].payload["dependencies"]
        assert deps[0]["name"] == "FluentValidation"
        assert deps[0]["declared_version"] == "11.8.0"

    @patch("nfr_review.collectors.csharp_deps.DepsDevClient")
    def test_package_name_is_include_attribute(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = CsharpDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        assert deps[0]["name"] == "Newtonsoft.Json"

    @patch("nfr_review.collectors.csharp_deps.DepsDevClient")
    def test_csproj_with_namespace(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        csproj = tmp_path / "Namespaced.csproj"
        csproj.write_text(
            '<Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003">\n'
            "  <ItemGroup>\n"
            '    <PackageReference Include="EntityFramework" Version="6.4.4" />\n'
            "  </ItemGroup>\n"
            "</Project>\n"
        )
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = CsharpDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert len(evidences) == 1
        deps = evidences[0].payload["dependencies"]
        assert deps[0]["name"] == "EntityFramework"
        assert deps[0]["declared_version"] == "6.4.4"


# ---------------------------------------------------------------------------
# deps.dev enrichment
# ---------------------------------------------------------------------------


class TestEnrichment:
    @patch("nfr_review.collectors.csharp_deps.DepsDevClient")
    def test_enriches_with_latest_version(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = CsharpDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        dep = evidences[0].payload["dependencies"][0]
        assert dep["latest_version"] == "9.9.9"
        assert dep["latest_release_date"] == "2025-01-01T00:00:00Z"
        assert dep["deps_dev_status"] == "ok"

    @patch("nfr_review.collectors.csharp_deps.DepsDevClient")
    def test_calls_deps_dev_with_nuget_ecosystem(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = CsharpDepsCollector()
        collector.collect(FIXTURE_DIR, None)
        calls = mock_cls.return_value.get_package_versions.call_args_list
        for call in calls:
            assert call[0][0] == "nuget"


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    @patch("nfr_review.collectors.csharp_deps.DepsDevClient")
    def test_produces_evidence_when_deps_dev_returns_none(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions.return_value = None
        collector = CsharpDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        assert len(evidences) == 1
        deps = evidences[0].payload["dependencies"]
        assert len(deps) > 0
        for dep in deps:
            assert dep["latest_version"] is None
            assert dep["deps_dev_status"] == "error"

    @patch("nfr_review.collectors.csharp_deps.DepsDevClient")
    def test_enrichment_errors_populated_on_failure(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions.return_value = None
        collector = CsharpDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        errors = evidences[0].payload["enrichment_errors"]
        assert len(errors) > 0
        assert all("error" in e for e in errors)

    @patch("nfr_review.collectors.csharp_deps.DepsDevClient")
    def test_partial_enrichment_failure(self, mock_cls: MagicMock) -> None:
        mapping = {
            "Newtonsoft.Json": _make_versions_response("13.0.4", "2024-11-15T00:00:00Z"),
            "Serilog": None,
        }
        mock_cls.return_value.get_package_versions = _mock_get_versions(mapping)
        collector = CsharpDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        by_name = {d["name"]: d for d in deps}
        assert by_name["Newtonsoft.Json"]["deps_dev_status"] == "ok"
        assert by_name["Newtonsoft.Json"]["latest_version"] == "13.0.4"
        assert by_name["Serilog"]["deps_dev_status"] == "error"
        assert by_name["Serilog"]["latest_version"] is None

    @patch("nfr_review.collectors.csharp_deps.DepsDevClient")
    def test_empty_versions_list_yields_not_found(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions.return_value = {"versions": []}
        collector = CsharpDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        for dep in evidences[0].payload["dependencies"]:
            assert dep["deps_dev_status"] == "not_found"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    @patch("nfr_review.collectors.csharp_deps.DepsDevClient")
    def test_empty_repo_returns_no_evidence(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        collector = CsharpDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert evidences == []

    @patch("nfr_review.collectors.csharp_deps.DepsDevClient")
    def test_csproj_with_no_package_references(
        self, mock_cls: MagicMock, tmp_path: Path
    ) -> None:
        csproj = tmp_path / "Empty.csproj"
        csproj.write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            "  <PropertyGroup>\n"
            "    <TargetFramework>net8.0</TargetFramework>\n"
            "  </PropertyGroup>\n"
            "  <ItemGroup>\n"
            "  </ItemGroup>\n"
            "</Project>\n"
        )
        collector = CsharpDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert evidences == []

    @patch("nfr_review.collectors.csharp_deps.DepsDevClient")
    def test_invalid_xml_skipped_gracefully(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        csproj = tmp_path / "Broken.csproj"
        csproj.write_text("this is not xml at all <broken>")
        collector = CsharpDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert evidences == []

    @patch("nfr_review.collectors.csharp_deps.DepsDevClient")
    def test_multiple_csproj_files(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        proj_a = tmp_path / "ProjectA.csproj"
        proj_a.write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            "  <ItemGroup>\n"
            '    <PackageReference Include="PkgA" Version="1.0.0" />\n'
            "  </ItemGroup>\n"
            "</Project>\n"
        )
        subdir = tmp_path / "src" / "ProjectB"
        subdir.mkdir(parents=True)
        proj_b = subdir / "ProjectB.csproj"
        proj_b.write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            "  <ItemGroup>\n"
            '    <PackageReference Include="PkgB" Version="2.0.0" />\n'
            "  </ItemGroup>\n"
            "</Project>\n"
        )
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = CsharpDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert len(evidences) == 1
        deps = evidences[0].payload["dependencies"]
        names = [d["name"] for d in deps]
        assert "PkgA" in names
        assert "PkgB" in names
        manifest_files = evidences[0].payload["manifest_files_found"]
        assert len(manifest_files) == 2

    @patch("nfr_review.collectors.csharp_deps.DepsDevClient")
    def test_csproj_in_bin_dir_skipped(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        bin_dir = tmp_path / "bin" / "Debug" / "net8.0"
        bin_dir.mkdir(parents=True)
        csproj = bin_dir / "App.csproj"
        csproj.write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            "  <ItemGroup>\n"
            '    <PackageReference Include="SkipMe" Version="1.0.0" />\n'
            "  </ItemGroup>\n"
            "</Project>\n"
        )
        collector = CsharpDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert evidences == []

    @patch("nfr_review.collectors.csharp_deps.DepsDevClient")
    def test_csproj_in_obj_dir_skipped(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        obj_dir = tmp_path / "obj"
        obj_dir.mkdir()
        csproj = obj_dir / "App.csproj"
        csproj.write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            "  <ItemGroup>\n"
            '    <PackageReference Include="SkipMe" Version="1.0.0" />\n'
            "  </ItemGroup>\n"
            "</Project>\n"
        )
        collector = CsharpDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert evidences == []

    @patch("nfr_review.collectors.csharp_deps.DepsDevClient")
    def test_package_reference_without_version(
        self, mock_cls: MagicMock, tmp_path: Path
    ) -> None:
        csproj = tmp_path / "NoVersion.csproj"
        csproj.write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            "  <ItemGroup>\n"
            '    <PackageReference Include="ImplicitVersion" />\n'
            "  </ItemGroup>\n"
            "</Project>\n"
        )
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = CsharpDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert len(evidences) == 1
        deps = evidences[0].payload["dependencies"]
        assert deps[0]["name"] == "ImplicitVersion"
        assert deps[0]["declared_version"] == ""

    @patch("nfr_review.collectors.csharp_deps.DepsDevClient")
    def test_manifest_files_found(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = CsharpDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        found = evidences[0].payload["manifest_files_found"]
        assert "SampleProject.csproj" in found

    @patch("nfr_review.collectors.csharp_deps.DepsDevClient")
    def test_csproj_with_no_item_group(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        csproj = tmp_path / "Minimal.csproj"
        csproj.write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            "  <PropertyGroup>\n"
            "    <TargetFramework>net8.0</TargetFramework>\n"
            "  </PropertyGroup>\n"
            "</Project>\n"
        )
        collector = CsharpDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert evidences == []
