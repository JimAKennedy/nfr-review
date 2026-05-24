# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""JDepend collector — invokes jdepend CLI on Java bytecode directories
and parses XML output to emit package-level coupling metrics.
"""

from __future__ import annotations

import logging
import subprocess  # nosec B404 — args are hardcoded, not user input
import xml.etree.ElementTree as ET  # nosec B405
from pathlib import Path
from typing import Any

from nfr_review.models import Evidence
from nfr_review.path_filter import compile_exclude_patterns, should_exclude_path
from nfr_review.registry import collector_registry

logger = logging.getLogger(__name__)

_SKIP_DIRS = {".git", "node_modules", ".gradle"}

_BYTECODE_PATTERNS = [
    "target/classes",
    "build/classes/java/main",
    "build/classes",
]

_BUILD_CONFIGS = {
    "pom.xml": (
        ["mvn", "compile", "-DskipTests", "-Denforcer.skip=true"],
        "target/classes",
    ),
    "build.gradle": (["gradle", "classes", "-x", "test"], "build/classes/java/main"),
    "build.gradle.kts": (["gradle", "classes", "-x", "test"], "build/classes/java/main"),
}


def _find_bytecode_dirs(repo_path: Path) -> list[Path]:
    """Search repo_path for directories matching known bytecode locations."""
    found: list[Path] = []
    for pattern in _BYTECODE_PATTERNS:
        for match in sorted(repo_path.rglob(pattern)):
            if not match.is_dir():
                continue
            if _SKIP_DIRS & set(match.relative_to(repo_path).parts):
                continue
            found.append(match)
    return found


def _resolve_build_cmd(repo_path: Path, config_file: str, cmd: list[str]) -> list[str]:
    """Prefer project-local wrapper scripts over system binaries."""
    tool = cmd[0]
    wrappers = {"mvn": "mvnw", "gradle": "gradlew"}
    wrapper_name = wrappers.get(tool)
    if wrapper_name:
        wrapper_path = repo_path / wrapper_name
        if wrapper_path.is_file():
            return [str(wrapper_path)] + cmd[1:]
    return cmd


def _try_compile_java(repo_path: Path) -> str | None:
    """Attempt to compile Java sources if a build config exists.

    Returns None on success or an error message on failure.
    """
    for config_file, (cmd, _expected_dir) in _BUILD_CONFIGS.items():
        if (repo_path / config_file).exists():
            resolved_cmd = _resolve_build_cmd(repo_path, config_file, cmd)
            tool_name = resolved_cmd[0]
            logger.info(
                "No bytecode found but %s detected — running '%s'",
                config_file,
                " ".join(resolved_cmd),
            )
            try:
                result = subprocess.run(  # nosec B603 B607
                    resolved_cmd,
                    cwd=str(repo_path),
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
            except FileNotFoundError:
                return (
                    f"{tool_name} not found on PATH — "
                    f"install {tool_name} or add a wrapper script to enable auto-compile"
                )
            except subprocess.SubprocessError as exc:
                return f"{tool_name} compile failed: {exc}"

            if result.returncode != 0:
                error_output = result.stderr or result.stdout or ""
                snippet = error_output.strip()[-500:]
                return f"{tool_name} compile exited with code {result.returncode}: {snippet}"

            logger.info("Auto-compile via %s succeeded", tool_name)
            return None

    return "no pom.xml or build.gradle found — cannot auto-compile"


def _parse_package_stats(pkg_el: ET.Element) -> dict[str, Any]:
    """Extract metrics from a <Package> element's <Stats> child."""
    stats_el = pkg_el.find("Stats")
    name = pkg_el.get("name", "unknown")

    metrics: dict[str, Any] = {"name": name}

    if stats_el is None:
        metrics.update(
            {
                "total_classes": 0,
                "concrete_classes": 0,
                "abstract_classes": 0,
                "ca": 0,
                "ce": 0,
                "a": 0.0,
                "i": 0.0,
                "d": 0.0,
                "v": 0,
            }
        )
        return metrics

    def _int(tag: str, default: int = 0) -> int:
        el = stats_el.find(tag)  # type: ignore[union-attr]
        if el is not None and el.text:
            try:
                return int(el.text)
            except ValueError:
                return default
        return default

    def _float(tag: str, default: float = 0.0) -> float:
        el = stats_el.find(tag)  # type: ignore[union-attr]
        if el is not None and el.text:
            try:
                return float(el.text)
            except ValueError:
                return default
        return default

    metrics["total_classes"] = _int("TotalClasses")
    metrics["concrete_classes"] = _int("ConcreteClasses")
    metrics["abstract_classes"] = _int("AbstractClasses")
    metrics["ca"] = _int("Ca")
    metrics["ce"] = _int("Ce")
    metrics["a"] = _float("A")
    metrics["i"] = _float("I")
    metrics["d"] = _float("D")
    metrics["v"] = _int("V")

    return metrics


def _parse_cycles(root: ET.Element) -> list[list[str]]:
    """Extract cycle groups from the <Cycles> section."""
    cycles_el = root.find("Cycles")
    if cycles_el is None:
        return []

    groups: list[list[str]] = []
    for pkg_el in cycles_el.findall("Package"):
        cycle_group: list[str] = []
        top_name = pkg_el.get("Name", "")
        if top_name:
            cycle_group.append(top_name)
        for child_pkg in pkg_el.findall("Package"):
            child_name = child_pkg.get("Name", "")
            if child_name:
                cycle_group.append(child_name)
        if cycle_group:
            groups.append(cycle_group)

    return groups


def _parse_jdepend_xml(xml_text: str) -> tuple[list[dict[str, Any]], list[list[str]]]:
    """Parse JDepend XML output, returning (packages, cycle_groups)."""
    root = ET.fromstring(xml_text)  # nosec B314

    packages: list[dict[str, Any]] = []
    packages_el = root.find("Packages")
    if packages_el is not None:
        for pkg_el in packages_el.findall("Package"):
            metrics = _parse_package_stats(pkg_el)
            packages.append(metrics)

    cycle_groups = _parse_cycles(root)
    return packages, cycle_groups


class JDependCollector:
    name = "jdepend"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        exclude_test = getattr(config, "exclude_test_paths", True)
        exclude_pats = compile_exclude_patterns(getattr(config, "exclude_paths", []))

        bytecode_dirs = _find_bytecode_dirs(repo_path)

        # Filter out excluded paths
        filtered_dirs: list[Path] = []
        for bd in bytecode_dirs:
            rel = str(bd.relative_to(repo_path))
            if not should_exclude_path(
                rel, exclude_test_paths=exclude_test, exclude_patterns=exclude_pats
            ):
                filtered_dirs.append(bd)

        if not filtered_dirs:
            has_java = any(repo_path.rglob("*.java"))
            if not has_java:
                return []

            compile_err = _try_compile_java(repo_path)
            if compile_err:
                logger.info(
                    "JDepend skipped: Java sources found but no bytecode — %s",
                    compile_err,
                )
                return []

            filtered_dirs = _find_bytecode_dirs(repo_path)
            filtered_dirs = [
                bd
                for bd in filtered_dirs
                if not should_exclude_path(
                    str(bd.relative_to(repo_path)),
                    exclude_test_paths=exclude_test,
                    exclude_patterns=exclude_pats,
                )
            ]
            if not filtered_dirs:
                logger.warning(
                    "JDepend skipped: auto-compile succeeded but no bytecode directories found"
                )
                return [
                    Evidence(
                        collector_name=self.name,
                        collector_version=self.version,
                        locator=".",
                        kind="jdepend-skip",
                        payload={
                            "reason": "Auto-compile succeeded but no bytecode "
                            "directories were produced"
                        },
                    )
                ]

        evidences: list[Evidence] = []

        for bytecode_dir in filtered_dirs:
            rel_dir = str(bytecode_dir.relative_to(repo_path))

            try:
                result = subprocess.run(  # nosec B603 B607
                    ["jdepend", str(bytecode_dir)],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
            except FileNotFoundError:
                logger.warning("jdepend binary not found; skipping JDepend analysis")
                return [
                    Evidence(
                        collector_name=self.name,
                        collector_version=self.version,
                        locator=".",
                        kind="jdepend-skip",
                        payload={
                            "reason": "jdepend binary not found — "
                            "install jdepend and ensure it is on PATH"
                        },
                    )
                ]
            except subprocess.SubprocessError as exc:
                logger.warning("jdepend failed: %s", exc)
                return [
                    Evidence(
                        collector_name=self.name,
                        collector_version=self.version,
                        locator=".",
                        kind="jdepend-skip",
                        payload={"reason": f"jdepend execution error: {exc}"},
                    )
                ]

            if result.returncode != 0:
                logger.warning(
                    "jdepend exited with code %d for %s", result.returncode, rel_dir
                )
                return [
                    Evidence(
                        collector_name=self.name,
                        collector_version=self.version,
                        locator=rel_dir,
                        kind="jdepend-skip",
                        payload={
                            "reason": f"jdepend exited with code {result.returncode}",
                            "stderr": result.stderr[:500] if result.stderr else "",
                        },
                    )
                ]

            xml_output = result.stdout
            try:
                packages, cycle_groups = _parse_jdepend_xml(xml_output)
            except ET.ParseError as exc:
                logger.warning("Failed to parse jdepend XML for %s: %s", rel_dir, exc)
                return [
                    Evidence(
                        collector_name=self.name,
                        collector_version=self.version,
                        locator=rel_dir,
                        kind="jdepend-skip",
                        payload={"reason": f"XML parse error: {exc}"},
                    )
                ]

            # Collect packages involved in cycles
            cycle_package_names: set[str] = set()
            for group in cycle_groups:
                cycle_package_names.update(group)

            distances = [p["d"] for p in packages]
            avg_distance = sum(distances) / len(distances) if distances else 0.0
            max_distance = max(distances) if distances else 0.0

            evidences.append(
                Evidence(
                    collector_name=self.name,
                    collector_version=self.version,
                    locator=rel_dir,
                    kind="jdepend-packages",
                    payload={
                        "bytecode_dir": rel_dir,
                        "packages": packages,
                    },
                )
            )

            evidences.append(
                Evidence(
                    collector_name=self.name,
                    collector_version=self.version,
                    locator=rel_dir,
                    kind="jdepend-summary",
                    payload={
                        "total_packages": len(packages),
                        "packages_with_cycles": len(cycle_package_names),
                        "cycle_groups": cycle_groups,
                        "avg_distance": round(avg_distance, 4),
                        "max_distance": round(max_distance, 4),
                    },
                )
            )

        return evidences


def _register() -> None:
    if "jdepend" not in collector_registry:
        collector_registry.register("jdepend", JDependCollector())


_register()


__all__ = ["JDependCollector"]
