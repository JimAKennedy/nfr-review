"""Tests for dependency collector path filtering — ensures fixture manifests
under test directories are excluded by default and included when
exclude_test_paths=False.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from nfr_review.config import Config


def _make_versions_response(version: str = "9.9.9") -> dict[str, Any]:
    return {
        "versions": [
            {
                "versionKey": {"version": version},
                "publishedAt": "2025-01-01T00:00:00Z",
            }
        ]
    }


def _mock_client() -> MagicMock:
    client = MagicMock()
    client.get_package_versions.return_value = _make_versions_response()
    client.prefetch_package_versions.return_value = None
    return client


# ---------------------------------------------------------------------------
# Python deps
# ---------------------------------------------------------------------------


class TestPythonDepsPathFilter:
    @patch("nfr_review.collectors.python_deps.DepsDevClient")
    def test_excludes_test_manifests(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        from nfr_review.collectors.python_deps import PythonDepsCollector

        (tmp_path / "requirements.txt").write_text("requests>=2.0\n")
        fixture_dir = tmp_path / "tests" / "fixtures" / "sample"
        fixture_dir.mkdir(parents=True)
        (fixture_dir / "requirements.txt").write_text("fakepkg>=1.0\n")

        mock_cls.return_value = _mock_client()
        results = PythonDepsCollector().collect(tmp_path, Config())

        assert len(results) == 1
        manifest_files = results[0].payload["manifest_files_found"]
        assert manifest_files == ["requirements.txt"]

    @patch("nfr_review.collectors.python_deps.DepsDevClient")
    def test_includes_test_manifests_when_disabled(
        self, mock_cls: MagicMock, tmp_path: Path
    ) -> None:
        from nfr_review.collectors.python_deps import PythonDepsCollector

        (tmp_path / "requirements.txt").write_text("requests>=2.0\n")
        fixture_dir = tmp_path / "tests" / "fixtures" / "sample"
        fixture_dir.mkdir(parents=True)
        (fixture_dir / "requirements.txt").write_text("fakepkg>=1.0\n")

        mock_cls.return_value = _mock_client()
        cfg = Config(exclude_test_paths=False)
        results = PythonDepsCollector().collect(tmp_path, cfg)

        assert len(results) == 1
        manifest_files = results[0].payload["manifest_files_found"]
        assert len(manifest_files) == 2
        assert "requirements.txt" in manifest_files
        assert "tests/fixtures/sample/requirements.txt" in manifest_files


# ---------------------------------------------------------------------------
# Go deps
# ---------------------------------------------------------------------------


class TestGoDepsPathFilter:
    _GO_MOD = """\
module example.com/mymod

go 1.21

require golang.org/x/text v0.14.0
"""

    @patch("nfr_review.collectors.go_deps.DepsDevClient")
    def test_excludes_test_manifests(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        from nfr_review.collectors.go_deps import GoDepsCollector

        (tmp_path / "go.mod").write_text(self._GO_MOD)
        fixture_dir = tmp_path / "tests" / "fixtures" / "go-sample"
        fixture_dir.mkdir(parents=True)
        (fixture_dir / "go.mod").write_text(self._GO_MOD)

        mock_cls.return_value = _mock_client()
        results = GoDepsCollector().collect(tmp_path, Config())

        assert len(results) == 1
        manifest_files = results[0].payload["manifest_files_found"]
        assert manifest_files == ["go.mod"]

    @patch("nfr_review.collectors.go_deps.DepsDevClient")
    def test_includes_test_manifests_when_disabled(
        self, mock_cls: MagicMock, tmp_path: Path
    ) -> None:
        from nfr_review.collectors.go_deps import GoDepsCollector

        (tmp_path / "go.mod").write_text(self._GO_MOD)
        fixture_dir = tmp_path / "tests" / "fixtures" / "go-sample"
        fixture_dir.mkdir(parents=True)
        (fixture_dir / "go.mod").write_text(self._GO_MOD)

        mock_cls.return_value = _mock_client()
        cfg = Config(exclude_test_paths=False)
        results = GoDepsCollector().collect(tmp_path, cfg)

        assert len(results) == 1
        manifest_files = results[0].payload["manifest_files_found"]
        assert len(manifest_files) == 2


# ---------------------------------------------------------------------------
# Java deps
# ---------------------------------------------------------------------------


class TestJavaDepsPathFilter:
    _POM_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<project>
  <dependencies>
    <dependency>
      <groupId>com.google.guava</groupId>
      <artifactId>guava</artifactId>
      <version>33.0.0</version>
    </dependency>
  </dependencies>
</project>
"""

    @patch("nfr_review.collectors.java_deps.DepsDevClient")
    def test_excludes_test_manifests(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        from nfr_review.collectors.java_deps import JavaDepsCollector

        (tmp_path / "pom.xml").write_text(self._POM_XML)
        fixture_dir = tmp_path / "tests" / "fixtures" / "java-sample"
        fixture_dir.mkdir(parents=True)
        (fixture_dir / "pom.xml").write_text(self._POM_XML)

        mock_cls.return_value = _mock_client()
        results = JavaDepsCollector().collect(tmp_path, Config())

        assert len(results) == 1
        manifest_files = results[0].payload["manifest_files_found"]
        assert manifest_files == ["pom.xml"]

    @patch("nfr_review.collectors.java_deps.DepsDevClient")
    def test_includes_test_manifests_when_disabled(
        self, mock_cls: MagicMock, tmp_path: Path
    ) -> None:
        from nfr_review.collectors.java_deps import JavaDepsCollector

        (tmp_path / "pom.xml").write_text(self._POM_XML)
        fixture_dir = tmp_path / "tests" / "fixtures" / "java-sample"
        fixture_dir.mkdir(parents=True)
        (fixture_dir / "pom.xml").write_text(self._POM_XML)

        mock_cls.return_value = _mock_client()
        cfg = Config(exclude_test_paths=False)
        results = JavaDepsCollector().collect(tmp_path, cfg)

        assert len(results) == 1
        manifest_files = results[0].payload["manifest_files_found"]
        assert len(manifest_files) == 2


# ---------------------------------------------------------------------------
# Node.js deps
# ---------------------------------------------------------------------------


class TestNodejsDepsPathFilter:
    _PKG_JSON = '{"dependencies": {"express": "^4.18.0"}}'

    @patch("nfr_review.collectors.nodejs_deps.DepsDevClient")
    def test_excludes_test_manifests(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        from nfr_review.collectors.nodejs_deps import NodejsDepsCollector

        (tmp_path / "package.json").write_text(self._PKG_JSON)
        fixture_dir = tmp_path / "tests" / "fixtures" / "node-sample"
        fixture_dir.mkdir(parents=True)
        (fixture_dir / "package.json").write_text(self._PKG_JSON)

        mock_cls.return_value = _mock_client()
        results = NodejsDepsCollector().collect(tmp_path, Config())

        assert len(results) == 1
        manifest_files = results[0].payload["manifest_files_found"]
        assert manifest_files == ["package.json"]

    @patch("nfr_review.collectors.nodejs_deps.DepsDevClient")
    def test_includes_test_manifests_when_disabled(
        self, mock_cls: MagicMock, tmp_path: Path
    ) -> None:
        from nfr_review.collectors.nodejs_deps import NodejsDepsCollector

        (tmp_path / "package.json").write_text(self._PKG_JSON)
        fixture_dir = tmp_path / "tests" / "fixtures" / "node-sample"
        fixture_dir.mkdir(parents=True)
        (fixture_dir / "package.json").write_text(self._PKG_JSON)

        mock_cls.return_value = _mock_client()
        cfg = Config(exclude_test_paths=False)
        results = NodejsDepsCollector().collect(tmp_path, cfg)

        assert len(results) == 1
        manifest_files = results[0].payload["manifest_files_found"]
        assert len(manifest_files) == 2


# ---------------------------------------------------------------------------
# C# deps
# ---------------------------------------------------------------------------


class TestCsharpDepsPathFilter:
    _CSPROJ = """\
<Project Sdk="Microsoft.NET.Sdk">
  <ItemGroup>
    <PackageReference Include="Newtonsoft.Json" Version="13.0.3" />
  </ItemGroup>
</Project>
"""

    @patch("nfr_review.collectors.csharp_deps.DepsDevClient")
    def test_excludes_test_manifests(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        from nfr_review.collectors.csharp_deps import CsharpDepsCollector

        (tmp_path / "App.csproj").write_text(self._CSPROJ)
        fixture_dir = tmp_path / "tests" / "fixtures" / "csharp-sample"
        fixture_dir.mkdir(parents=True)
        (fixture_dir / "TestApp.csproj").write_text(self._CSPROJ)

        mock_cls.return_value = _mock_client()
        results = CsharpDepsCollector().collect(tmp_path, Config())

        assert len(results) == 1
        manifest_files = results[0].payload["manifest_files_found"]
        assert manifest_files == ["App.csproj"]

    @patch("nfr_review.collectors.csharp_deps.DepsDevClient")
    def test_includes_test_manifests_when_disabled(
        self, mock_cls: MagicMock, tmp_path: Path
    ) -> None:
        from nfr_review.collectors.csharp_deps import CsharpDepsCollector

        (tmp_path / "App.csproj").write_text(self._CSPROJ)
        fixture_dir = tmp_path / "tests" / "fixtures" / "csharp-sample"
        fixture_dir.mkdir(parents=True)
        (fixture_dir / "TestApp.csproj").write_text(self._CSPROJ)

        mock_cls.return_value = _mock_client()
        cfg = Config(exclude_test_paths=False)
        results = CsharpDepsCollector().collect(tmp_path, cfg)

        assert len(results) == 1
        manifest_files = results[0].payload["manifest_files_found"]
        assert len(manifest_files) == 2
