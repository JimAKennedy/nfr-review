"""Tests for JDependCollector — registration, discovery, parsing, cycles, degradation."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nfr_review.collectors.jdepend import JDependCollector
from nfr_review.registry import collector_registry

# ---------------------------------------------------------------------------
# Sample XML
# ---------------------------------------------------------------------------

SAMPLE_XML = """\
<?xml version="1.0"?>
<JDepend>
  <Packages>
    <Package name="com.example.core">
      <Stats>
        <TotalClasses>10</TotalClasses>
        <ConcreteClasses>8</ConcreteClasses>
        <AbstractClasses>2</AbstractClasses>
        <Ca>3</Ca>
        <Ce>5</Ce>
        <A>0.2</A>
        <I>0.63</I>
        <D>0.17</D>
        <V>1</V>
      </Stats>
    </Package>
    <Package name="com.example.util">
      <Stats>
        <TotalClasses>5</TotalClasses>
        <ConcreteClasses>5</ConcreteClasses>
        <AbstractClasses>0</AbstractClasses>
        <Ca>7</Ca>
        <Ce>1</Ce>
        <A>0.0</A>
        <I>0.13</I>
        <D>0.87</D>
        <V>1</V>
      </Stats>
    </Package>
  </Packages>
  <Cycles>
  </Cycles>
</JDepend>
"""

SAMPLE_XML_WITH_CYCLES = """\
<?xml version="1.0"?>
<JDepend>
  <Packages>
    <Package name="com.example.a">
      <Stats>
        <TotalClasses>3</TotalClasses>
        <ConcreteClasses>3</ConcreteClasses>
        <AbstractClasses>0</AbstractClasses>
        <Ca>1</Ca>
        <Ce>2</Ce>
        <A>0.0</A>
        <I>0.67</I>
        <D>0.33</D>
        <V>1</V>
      </Stats>
    </Package>
    <Package name="com.example.b">
      <Stats>
        <TotalClasses>2</TotalClasses>
        <ConcreteClasses>2</ConcreteClasses>
        <AbstractClasses>0</AbstractClasses>
        <Ca>2</Ca>
        <Ce>1</Ce>
        <A>0.0</A>
        <I>0.33</I>
        <D>0.67</D>
        <V>1</V>
      </Stats>
    </Package>
    <Package name="com.example.c">
      <Stats>
        <TotalClasses>1</TotalClasses>
        <ConcreteClasses>1</ConcreteClasses>
        <AbstractClasses>0</AbstractClasses>
        <Ca>0</Ca>
        <Ce>1</Ce>
        <A>0.0</A>
        <I>1.0</I>
        <D>0.0</D>
        <V>1</V>
      </Stats>
    </Package>
  </Packages>
  <Cycles>
    <Package Name="com.example.a">
      <Package Name="com.example.b"/>
    </Package>
  </Cycles>
</JDepend>
"""

SAMPLE_XML_MISSING_STATS = """\
<?xml version="1.0"?>
<JDepend>
  <Packages>
    <Package name="com.example.empty">
    </Package>
  </Packages>
  <Cycles/>
</JDepend>
"""

SAMPLE_XML_NO_CYCLES_SECTION = """\
<?xml version="1.0"?>
<JDepend>
  <Packages>
    <Package name="com.example.solo">
      <Stats>
        <TotalClasses>1</TotalClasses>
        <ConcreteClasses>1</ConcreteClasses>
        <AbstractClasses>0</AbstractClasses>
        <Ca>0</Ca>
        <Ce>0</Ce>
        <A>0.0</A>
        <I>0.0</I>
        <D>1.0</D>
        <V>1</V>
      </Stats>
    </Package>
  </Packages>
</JDepend>
"""


def _make_bytecode_dir(tmp_path: Path, rel: str = "target/classes") -> Path:
    """Create a bytecode directory under tmp_path and return tmp_path (repo root)."""
    d = tmp_path / rel
    d.mkdir(parents=True, exist_ok=True)
    # Put a dummy class file so the dir is non-empty
    (d / "Dummy.class").write_bytes(b"\xca\xfe\xba\xbe")
    return tmp_path


def _mock_subprocess_run(xml_output: str) -> MagicMock:
    """Return a mock for subprocess.run that returns the given XML."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = xml_output
    mock_result.stderr = ""
    return MagicMock(return_value=mock_result)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_registered_in_collector_registry(self) -> None:
        assert "jdepend" in collector_registry

    def test_collector_name_and_version(self) -> None:
        collector = JDependCollector()
        assert collector.name == "jdepend"
        assert collector.version == "0.1.0"


# ---------------------------------------------------------------------------
# Bytecode discovery
# ---------------------------------------------------------------------------


class TestBytecodeDiscovery:
    def test_finds_target_classes(self, tmp_path: Path) -> None:
        repo = _make_bytecode_dir(tmp_path, "target/classes")
        from nfr_review.collectors.jdepend import _find_bytecode_dirs

        dirs = _find_bytecode_dirs(repo)
        assert len(dirs) == 1
        assert dirs[0] == repo / "target" / "classes"

    def test_finds_gradle_classes(self, tmp_path: Path) -> None:
        repo = _make_bytecode_dir(tmp_path, "build/classes/java/main")
        from nfr_review.collectors.jdepend import _find_bytecode_dirs

        dirs = _find_bytecode_dirs(repo)
        assert len(dirs) >= 1
        paths_str = [str(d) for d in dirs]
        assert any("build/classes/java/main" in p for p in paths_str)

    def test_finds_build_classes(self, tmp_path: Path) -> None:
        repo = _make_bytecode_dir(tmp_path, "build/classes")
        from nfr_review.collectors.jdepend import _find_bytecode_dirs

        dirs = _find_bytecode_dirs(repo)
        assert len(dirs) >= 1
        paths_str = [str(d) for d in dirs]
        assert any("build/classes" in p for p in paths_str)

    def test_finds_nested_module_bytecode(self, tmp_path: Path) -> None:
        repo = _make_bytecode_dir(tmp_path, "module-a/target/classes")
        from nfr_review.collectors.jdepend import _find_bytecode_dirs

        dirs = _find_bytecode_dirs(repo)
        assert len(dirs) == 1
        assert "module-a" in str(dirs[0])

    def test_skips_node_modules(self, tmp_path: Path) -> None:
        d = tmp_path / "node_modules" / "some-pkg" / "target" / "classes"
        d.mkdir(parents=True)
        from nfr_review.collectors.jdepend import _find_bytecode_dirs

        dirs = _find_bytecode_dirs(tmp_path)
        assert len(dirs) == 0

    def test_no_bytecode_dirs_no_java_returns_empty(self, tmp_path: Path) -> None:
        collector = JDependCollector()
        evidences = collector.collect(tmp_path, None)
        assert evidences == []

    @patch("nfr_review.collectors.jdepend.subprocess.run")
    def test_no_bytecode_with_java_and_pom_triggers_compile(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        (tmp_path / "src/main/java/App.java").parent.mkdir(parents=True)
        (tmp_path / "src/main/java/App.java").write_text("class App {}")
        (tmp_path / "pom.xml").write_text("<project/>")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        collector = JDependCollector()
        collector.collect(tmp_path, None)
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0] == "mvn"

    @patch("nfr_review.collectors.jdepend.subprocess.run")
    def test_no_bytecode_compile_failure_returns_skip(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        (tmp_path / "src/main/java/App.java").parent.mkdir(parents=True)
        (tmp_path / "src/main/java/App.java").write_text("class App {}")
        (tmp_path / "pom.xml").write_text("<project/>")

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "BUILD FAILURE"
        mock_run.return_value = mock_result

        collector = JDependCollector()
        evidences = collector.collect(tmp_path, None)
        assert len(evidences) == 1
        assert evidences[0].kind == "jdepend-skip"
        assert "Auto-compile failed" in evidences[0].payload["reason"]

    @patch("nfr_review.collectors.jdepend.subprocess.run")
    def test_no_bytecode_no_build_config_returns_skip(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        (tmp_path / "src/main/java/App.java").parent.mkdir(parents=True)
        (tmp_path / "src/main/java/App.java").write_text("class App {}")

        collector = JDependCollector()
        evidences = collector.collect(tmp_path, None)
        assert len(evidences) == 1
        assert evidences[0].kind == "jdepend-skip"
        assert "no pom.xml" in evidences[0].payload["reason"]

    @patch("nfr_review.collectors.jdepend.subprocess.run")
    def test_prefers_mvnw_wrapper_over_system_mvn(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        (tmp_path / "src/main/java/App.java").parent.mkdir(parents=True)
        (tmp_path / "src/main/java/App.java").write_text("class App {}")
        (tmp_path / "pom.xml").write_text("<project/>")
        (tmp_path / "mvnw").write_text('#!/bin/sh\nexec mvn "$@"')

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        collector = JDependCollector()
        collector.collect(tmp_path, None)
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0] == str(tmp_path / "mvnw")

    @patch("nfr_review.collectors.jdepend.subprocess.run")
    def test_prefers_gradlew_wrapper_over_system_gradle(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        (tmp_path / "src/main/java/App.java").parent.mkdir(parents=True)
        (tmp_path / "src/main/java/App.java").write_text("class App {}")
        (tmp_path / "build.gradle").write_text("apply plugin: 'java'")
        (tmp_path / "gradlew").write_text('#!/bin/sh\nexec gradle "$@"')

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        collector = JDependCollector()
        collector.collect(tmp_path, None)
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0] == str(tmp_path / "gradlew")


# ---------------------------------------------------------------------------
# JDepend not installed
# ---------------------------------------------------------------------------


class TestJDependNotInstalled:
    @patch("nfr_review.collectors.jdepend.subprocess.run")
    def test_file_not_found_returns_skip(self, mock_run: MagicMock, tmp_path: Path) -> None:
        _make_bytecode_dir(tmp_path)
        mock_run.side_effect = FileNotFoundError("jdepend not found")
        collector = JDependCollector()
        evidences = collector.collect(tmp_path, None)
        assert len(evidences) == 1
        assert evidences[0].kind == "jdepend-skip"
        assert "not found" in evidences[0].payload["reason"]

    @patch("nfr_review.collectors.jdepend.subprocess.run")
    def test_subprocess_error_returns_skip(self, mock_run: MagicMock, tmp_path: Path) -> None:
        _make_bytecode_dir(tmp_path)
        mock_run.side_effect = subprocess.SubprocessError("timeout")
        collector = JDependCollector()
        evidences = collector.collect(tmp_path, None)
        assert len(evidences) == 1
        assert evidences[0].kind == "jdepend-skip"
        assert "error" in evidences[0].payload["reason"]

    @patch("nfr_review.collectors.jdepend.subprocess.run")
    def test_nonzero_exit_returns_skip(self, mock_run: MagicMock, tmp_path: Path) -> None:
        _make_bytecode_dir(tmp_path)
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "error: no classes found"
        mock_run.return_value = mock_result
        collector = JDependCollector()
        evidences = collector.collect(tmp_path, None)
        assert len(evidences) == 1
        assert evidences[0].kind == "jdepend-skip"
        assert "code 1" in evidences[0].payload["reason"]


# ---------------------------------------------------------------------------
# XML parsing
# ---------------------------------------------------------------------------


class TestXmlParsing:
    @patch("nfr_review.collectors.jdepend.subprocess.run")
    def test_parses_package_metrics(self, mock_run: MagicMock, tmp_path: Path) -> None:
        _make_bytecode_dir(tmp_path)
        mock_run.return_value = _mock_subprocess_run(SAMPLE_XML).return_value
        collector = JDependCollector()
        evidences = collector.collect(tmp_path, None)

        pkg_evidence = [e for e in evidences if e.kind == "jdepend-packages"]
        assert len(pkg_evidence) == 1
        packages = pkg_evidence[0].payload["packages"]
        assert len(packages) == 2

        core = next(p for p in packages if p["name"] == "com.example.core")
        assert core["ca"] == 3
        assert core["ce"] == 5
        assert core["a"] == 0.2
        assert core["i"] == 0.63
        assert core["d"] == 0.17
        assert core["v"] == 1
        assert core["total_classes"] == 10

    @patch("nfr_review.collectors.jdepend.subprocess.run")
    def test_parses_summary(self, mock_run: MagicMock, tmp_path: Path) -> None:
        _make_bytecode_dir(tmp_path)
        mock_run.return_value = _mock_subprocess_run(SAMPLE_XML).return_value
        collector = JDependCollector()
        evidences = collector.collect(tmp_path, None)

        summary = [e for e in evidences if e.kind == "jdepend-summary"]
        assert len(summary) == 1
        payload = summary[0].payload
        assert payload["total_packages"] == 2
        assert payload["packages_with_cycles"] == 0
        assert payload["cycle_groups"] == []

    @patch("nfr_review.collectors.jdepend.subprocess.run")
    def test_missing_stats_uses_defaults(self, mock_run: MagicMock, tmp_path: Path) -> None:
        _make_bytecode_dir(tmp_path)
        mock_run.return_value = _mock_subprocess_run(SAMPLE_XML_MISSING_STATS).return_value
        collector = JDependCollector()
        evidences = collector.collect(tmp_path, None)

        pkg_evidence = [e for e in evidences if e.kind == "jdepend-packages"]
        packages = pkg_evidence[0].payload["packages"]
        assert len(packages) == 1
        pkg = packages[0]
        assert pkg["name"] == "com.example.empty"
        assert pkg["ca"] == 0
        assert pkg["ce"] == 0
        assert pkg["a"] == 0.0
        assert pkg["i"] == 0.0
        assert pkg["d"] == 0.0

    @patch("nfr_review.collectors.jdepend.subprocess.run")
    def test_no_cycles_section(self, mock_run: MagicMock, tmp_path: Path) -> None:
        _make_bytecode_dir(tmp_path)
        mock_run.return_value = _mock_subprocess_run(SAMPLE_XML_NO_CYCLES_SECTION).return_value
        collector = JDependCollector()
        evidences = collector.collect(tmp_path, None)

        summary = [e for e in evidences if e.kind == "jdepend-summary"]
        assert summary[0].payload["cycle_groups"] == []
        assert summary[0].payload["packages_with_cycles"] == 0

    @patch("nfr_review.collectors.jdepend.subprocess.run")
    def test_xml_parse_error_returns_skip(self, mock_run: MagicMock, tmp_path: Path) -> None:
        _make_bytecode_dir(tmp_path)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "this is not valid xml"
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        collector = JDependCollector()
        evidences = collector.collect(tmp_path, None)
        assert len(evidences) == 1
        assert evidences[0].kind == "jdepend-skip"
        assert "XML parse error" in evidences[0].payload["reason"]


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------


class TestCycleDetection:
    @patch("nfr_review.collectors.jdepend.subprocess.run")
    def test_detects_cycle_groups(self, mock_run: MagicMock, tmp_path: Path) -> None:
        _make_bytecode_dir(tmp_path)
        mock_run.return_value = _mock_subprocess_run(SAMPLE_XML_WITH_CYCLES).return_value
        collector = JDependCollector()
        evidences = collector.collect(tmp_path, None)

        summary = [e for e in evidences if e.kind == "jdepend-summary"]
        assert len(summary) == 1
        payload = summary[0].payload
        assert payload["packages_with_cycles"] == 2
        assert len(payload["cycle_groups"]) == 1
        assert "com.example.a" in payload["cycle_groups"][0]
        assert "com.example.b" in payload["cycle_groups"][0]

    @patch("nfr_review.collectors.jdepend.subprocess.run")
    def test_cycle_groups_structure(self, mock_run: MagicMock, tmp_path: Path) -> None:
        _make_bytecode_dir(tmp_path)
        mock_run.return_value = _mock_subprocess_run(SAMPLE_XML_WITH_CYCLES).return_value
        collector = JDependCollector()
        evidences = collector.collect(tmp_path, None)

        summary = [e for e in evidences if e.kind == "jdepend-summary"]
        cycle_groups = summary[0].payload["cycle_groups"]
        # Each group is a list of package name strings
        for group in cycle_groups:
            assert isinstance(group, list)
            for name in group:
                assert isinstance(name, str)


# ---------------------------------------------------------------------------
# Evidence shape
# ---------------------------------------------------------------------------


class TestEvidenceShape:
    @patch("nfr_review.collectors.jdepend.subprocess.run")
    def test_produces_packages_and_summary(self, mock_run: MagicMock, tmp_path: Path) -> None:
        _make_bytecode_dir(tmp_path)
        mock_run.return_value = _mock_subprocess_run(SAMPLE_XML).return_value
        collector = JDependCollector()
        evidences = collector.collect(tmp_path, None)
        kinds = {e.kind for e in evidences}
        assert "jdepend-packages" in kinds
        assert "jdepend-summary" in kinds

    @patch("nfr_review.collectors.jdepend.subprocess.run")
    def test_packages_payload_keys(self, mock_run: MagicMock, tmp_path: Path) -> None:
        _make_bytecode_dir(tmp_path)
        mock_run.return_value = _mock_subprocess_run(SAMPLE_XML).return_value
        collector = JDependCollector()
        evidences = collector.collect(tmp_path, None)
        pkg_ev = [e for e in evidences if e.kind == "jdepend-packages"][0]
        assert "bytecode_dir" in pkg_ev.payload
        assert "packages" in pkg_ev.payload

    @patch("nfr_review.collectors.jdepend.subprocess.run")
    def test_summary_payload_keys(self, mock_run: MagicMock, tmp_path: Path) -> None:
        _make_bytecode_dir(tmp_path)
        mock_run.return_value = _mock_subprocess_run(SAMPLE_XML).return_value
        collector = JDependCollector()
        evidences = collector.collect(tmp_path, None)
        summary_ev = [e for e in evidences if e.kind == "jdepend-summary"][0]
        expected_keys = {
            "total_packages",
            "packages_with_cycles",
            "cycle_groups",
            "avg_distance",
            "max_distance",
        }
        assert expected_keys <= set(summary_ev.payload.keys())

    @patch("nfr_review.collectors.jdepend.subprocess.run")
    def test_evidence_collector_metadata(self, mock_run: MagicMock, tmp_path: Path) -> None:
        _make_bytecode_dir(tmp_path)
        mock_run.return_value = _mock_subprocess_run(SAMPLE_XML).return_value
        collector = JDependCollector()
        evidences = collector.collect(tmp_path, None)
        for ev in evidences:
            assert ev.collector_name == "jdepend"
            assert ev.collector_version == "0.1.0"

    @patch("nfr_review.collectors.jdepend.subprocess.run")
    def test_avg_and_max_distance(self, mock_run: MagicMock, tmp_path: Path) -> None:
        _make_bytecode_dir(tmp_path)
        mock_run.return_value = _mock_subprocess_run(SAMPLE_XML).return_value
        collector = JDependCollector()
        evidences = collector.collect(tmp_path, None)
        summary_ev = [e for e in evidences if e.kind == "jdepend-summary"][0]
        # core.d=0.17, util.d=0.87 => avg=0.52, max=0.87
        assert summary_ev.payload["avg_distance"] == pytest.approx(0.52, abs=0.01)
        assert summary_ev.payload["max_distance"] == pytest.approx(0.87, abs=0.01)
