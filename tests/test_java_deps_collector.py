"""Tests for JavaDepsCollector — registration, parsing, enrichment, degradation."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from nfr_review.collectors.java_deps import JavaDepsCollector
from nfr_review.registry import collector_registry

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "java-deps-sample-repo"


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
        assert "java-deps" in collector_registry

    def test_collector_name_and_version(self) -> None:
        collector = JavaDepsCollector()
        assert collector.name == "java-deps"
        assert collector.version == "0.1.0"


# ---------------------------------------------------------------------------
# Evidence shape
# ---------------------------------------------------------------------------


class TestEvidenceShape:
    @patch("nfr_review.collectors.java_deps.DepsDevClient")
    def test_evidence_kind_is_java_deps(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = JavaDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        assert len(evidences) == 1
        assert evidences[0].kind == "java-deps"

    @patch("nfr_review.collectors.java_deps.DepsDevClient")
    def test_payload_has_required_top_level_keys(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = JavaDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        payload = evidences[0].payload
        assert "dependencies" in payload
        assert "manifest_files_found" in payload
        assert "enrichment_errors" in payload

    @patch("nfr_review.collectors.java_deps.DepsDevClient")
    def test_each_dependency_has_required_keys(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = JavaDepsCollector()
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
# pom.xml parsing
# ---------------------------------------------------------------------------


class TestPomXmlParsing:
    @patch("nfr_review.collectors.java_deps.DepsDevClient")
    def test_parses_dependencies_with_namespace(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = JavaDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        pom_deps = [d for d in deps if d["source_file"] == "pom.xml"]
        names = [d["name"] for d in pom_deps]
        assert "org.springframework:spring-core" in names
        assert "com.google.guava:guava" in names
        assert "junit:junit" in names
        assert "org.slf4j:slf4j-api" in names

    @patch("nfr_review.collectors.java_deps.DepsDevClient")
    def test_extracts_group_artifact_as_name(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = JavaDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        pom_deps = [d for d in deps if d["source_file"] == "pom.xml"]
        for dep in pom_deps:
            assert ":" in dep["name"]

    @patch("nfr_review.collectors.java_deps.DepsDevClient")
    def test_handles_missing_version(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = JavaDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        by_name = {d["name"]: d for d in deps}
        assert by_name["org.slf4j:slf4j-api"]["declared_version"] == ""

    @patch("nfr_review.collectors.java_deps.DepsDevClient")
    def test_handles_scope(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = JavaDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        by_name = {d["name"]: d for d in deps}
        assert by_name["junit:junit"]["scope"] == "test"
        assert "scope" not in by_name["org.springframework:spring-core"]

    @patch("nfr_review.collectors.java_deps.DepsDevClient")
    def test_pom_without_namespace(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        pom = tmp_path / "pom.xml"
        pom.write_text(
            '<?xml version="1.0"?>\n'
            "<project>\n"
            "  <dependencies>\n"
            "    <dependency>\n"
            "      <groupId>commons-io</groupId>\n"
            "      <artifactId>commons-io</artifactId>\n"
            "      <version>2.11.0</version>\n"
            "    </dependency>\n"
            "  </dependencies>\n"
            "</project>\n"
        )
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = JavaDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert len(evidences) == 1
        deps = evidences[0].payload["dependencies"]
        assert deps[0]["name"] == "commons-io:commons-io"
        assert deps[0]["declared_version"] == "2.11.0"

    @patch("nfr_review.collectors.java_deps.DepsDevClient")
    def test_variable_version_reference(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        pom = tmp_path / "pom.xml"
        pom.write_text(
            '<?xml version="1.0"?>\n'
            "<project>\n"
            "  <dependencies>\n"
            "    <dependency>\n"
            "      <groupId>org.apache</groupId>\n"
            "      <artifactId>commons-lang3</artifactId>\n"
            "      <version>${commons.version}</version>\n"
            "    </dependency>\n"
            "  </dependencies>\n"
            "</project>\n"
        )
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = JavaDepsCollector()
        evidences = collector.collect(tmp_path, None)
        deps = evidences[0].payload["dependencies"]
        assert deps[0]["declared_version"] == "${commons.version}"


# ---------------------------------------------------------------------------
# build.gradle parsing
# ---------------------------------------------------------------------------


class TestBuildGradleParsing:
    @patch("nfr_review.collectors.java_deps.DepsDevClient")
    def test_extracts_implementation_deps(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = JavaDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        gradle_deps = [d for d in deps if d["source_file"] == "build.gradle"]
        names = [d["name"] for d in gradle_deps]
        assert "com.fasterxml.jackson.core:jackson-databind" in names

    @patch("nfr_review.collectors.java_deps.DepsDevClient")
    def test_extracts_api_deps(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = JavaDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        gradle_deps = [d for d in deps if d["source_file"] == "build.gradle"]
        names = [d["name"] for d in gradle_deps]
        assert "io.netty:netty-all" in names

    @patch("nfr_review.collectors.java_deps.DepsDevClient")
    def test_extracts_test_implementation_deps(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = JavaDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        gradle_deps = [d for d in deps if d["source_file"] == "build.gradle"]
        names = [d["name"] for d in gradle_deps]
        assert "org.mockito:mockito-core" in names

    @patch("nfr_review.collectors.java_deps.DepsDevClient")
    def test_handles_both_quote_styles(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = JavaDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        gradle_deps = [d for d in deps if d["source_file"] == "build.gradle"]
        assert len(gradle_deps) == 3

    @patch("nfr_review.collectors.java_deps.DepsDevClient")
    def test_kotlin_dsl_syntax(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        gradle_kts = tmp_path / "build.gradle.kts"
        gradle_kts.write_text(
            'plugins {\n    id("java")\n}\n'
            "dependencies {\n"
            '    implementation("org.jetbrains.kotlin:kotlin-stdlib:1.9.0")\n'
            '    testImplementation("org.junit.jupiter:junit-jupiter:5.10.0")\n'
            "}\n"
        )
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = JavaDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert len(evidences) == 1
        deps = evidences[0].payload["dependencies"]
        names = [d["name"] for d in deps]
        assert "org.jetbrains.kotlin:kotlin-stdlib" in names
        assert "org.junit.jupiter:junit-jupiter" in names


# ---------------------------------------------------------------------------
# deps.dev enrichment
# ---------------------------------------------------------------------------


class TestEnrichment:
    @patch("nfr_review.collectors.java_deps.DepsDevClient")
    def test_enriches_with_latest_version(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = JavaDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        dep = evidences[0].payload["dependencies"][0]
        assert dep["latest_version"] == "9.9.9"
        assert dep["latest_release_date"] == "2025-01-01T00:00:00Z"
        assert dep["deps_dev_status"] == "ok"

    @patch("nfr_review.collectors.java_deps.DepsDevClient")
    def test_calls_deps_dev_with_maven_ecosystem(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = JavaDepsCollector()
        collector.collect(FIXTURE_DIR, None)
        calls = mock_cls.return_value.get_package_versions.call_args_list
        for call in calls:
            assert call[0][0] == "maven"


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    @patch("nfr_review.collectors.java_deps.DepsDevClient")
    def test_produces_evidence_when_deps_dev_returns_none(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions.return_value = None
        collector = JavaDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        assert len(evidences) == 1
        deps = evidences[0].payload["dependencies"]
        assert len(deps) > 0
        for dep in deps:
            assert dep["latest_version"] is None
            assert dep["deps_dev_status"] == "error"

    @patch("nfr_review.collectors.java_deps.DepsDevClient")
    def test_enrichment_errors_populated_on_failure(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions.return_value = None
        collector = JavaDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        errors = evidences[0].payload["enrichment_errors"]
        assert len(errors) > 0
        assert all("error" in e for e in errors)

    @patch("nfr_review.collectors.java_deps.DepsDevClient")
    def test_partial_enrichment_failure(self, mock_cls: MagicMock) -> None:
        mapping = {
            "org.springframework:spring-core": _make_versions_response(
                "6.1.0", "2024-11-15T00:00:00Z"
            ),
            "com.google.guava:guava": None,
        }
        mock_cls.return_value.get_package_versions = _mock_get_versions(mapping)
        collector = JavaDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        deps = evidences[0].payload["dependencies"]
        by_name = {d["name"]: d for d in deps}
        assert by_name["org.springframework:spring-core"]["deps_dev_status"] == "ok"
        assert by_name["org.springframework:spring-core"]["latest_version"] == "6.1.0"
        assert by_name["com.google.guava:guava"]["deps_dev_status"] == "error"
        assert by_name["com.google.guava:guava"]["latest_version"] is None

    @patch("nfr_review.collectors.java_deps.DepsDevClient")
    def test_empty_versions_list_yields_not_found(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions.return_value = {"versions": []}
        collector = JavaDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        for dep in evidences[0].payload["dependencies"]:
            assert dep["deps_dev_status"] == "not_found"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    @patch("nfr_review.collectors.java_deps.DepsDevClient")
    def test_empty_repo_returns_no_evidence(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        collector = JavaDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert evidences == []

    @patch("nfr_review.collectors.java_deps.DepsDevClient")
    def test_pom_with_no_dependencies(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        pom = tmp_path / "pom.xml"
        pom.write_text(
            '<?xml version="1.0"?>\n'
            '<project xmlns="http://maven.apache.org/POM/4.0.0">\n'
            "  <modelVersion>4.0.0</modelVersion>\n"
            "  <groupId>com.example</groupId>\n"
            "  <artifactId>empty</artifactId>\n"
            "  <version>1.0.0</version>\n"
            "</project>\n"
        )
        collector = JavaDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert evidences == []

    @patch("nfr_review.collectors.java_deps.DepsDevClient")
    def test_invalid_xml_skipped_gracefully(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        pom = tmp_path / "pom.xml"
        pom.write_text("this is not xml at all <broken>")
        collector = JavaDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert evidences == []

    @patch("nfr_review.collectors.java_deps.DepsDevClient")
    def test_nested_pom_xml(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        subdir = tmp_path / "module-a"
        subdir.mkdir()
        pom = subdir / "pom.xml"
        pom.write_text(
            '<?xml version="1.0"?>\n'
            "<project>\n"
            "  <dependencies>\n"
            "    <dependency>\n"
            "      <groupId>org.apache</groupId>\n"
            "      <artifactId>commons-lang3</artifactId>\n"
            "      <version>3.12.0</version>\n"
            "    </dependency>\n"
            "  </dependencies>\n"
            "</project>\n"
        )
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = JavaDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert len(evidences) == 1
        deps = evidences[0].payload["dependencies"]
        assert deps[0]["name"] == "org.apache:commons-lang3"
        assert "module-a/pom.xml" in deps[0]["source_file"]

    @patch("nfr_review.collectors.java_deps.DepsDevClient")
    def test_pom_in_target_dir_skipped(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        target = tmp_path / "target" / "generated"
        target.mkdir(parents=True)
        pom = target / "pom.xml"
        pom.write_text(
            '<?xml version="1.0"?>\n'
            "<project>\n"
            "  <dependencies>\n"
            "    <dependency>\n"
            "      <groupId>org.example</groupId>\n"
            "      <artifactId>skip-me</artifactId>\n"
            "      <version>1.0.0</version>\n"
            "    </dependency>\n"
            "  </dependencies>\n"
            "</project>\n"
        )
        collector = JavaDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert evidences == []

    @patch("nfr_review.collectors.java_deps.DepsDevClient")
    def test_gradle_in_build_dir_skipped(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        build_dir = tmp_path / "build" / "generated"
        build_dir.mkdir(parents=True)
        gradle = build_dir / "build.gradle"
        gradle.write_text("dependencies {\n    implementation 'a.b:c:1.0'\n}\n")
        collector = JavaDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert evidences == []

    @patch("nfr_review.collectors.java_deps.DepsDevClient")
    def test_gradle_with_no_deps(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        gradle = tmp_path / "build.gradle"
        gradle.write_text("plugins {\n    id 'java'\n}\n")
        collector = JavaDepsCollector()
        evidences = collector.collect(tmp_path, None)
        assert evidences == []

    @patch("nfr_review.collectors.java_deps.DepsDevClient")
    def test_manifest_files_found(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.get_package_versions = _mock_get_versions()
        collector = JavaDepsCollector()
        evidences = collector.collect(FIXTURE_DIR, None)
        found = evidences[0].payload["manifest_files_found"]
        assert "pom.xml" in found
        assert "build.gradle" in found
