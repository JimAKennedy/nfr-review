# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Auto-detect technologies present in a repository."""

from __future__ import annotations

import fnmatch
import logging
import os
from collections.abc import Callable
from pathlib import Path

from nfr_review.arch_utils import safe_read_text as _safe_read_text
from nfr_review.path_filter import ALWAYS_SKIP_DIRS, should_exclude_path

logger = logging.getLogger(__name__)

ALL_TECH_KEYS: list[str] = [
    "java",
    "spring_boot",
    "kubernetes",
    "apim",
    "ci",
    "adr",
    "dockerfile",
    "grpc",
    "go",
    "rust",
    "python",
    "nodejs",
    "csharp",
    "istio",
    "otel",
    "helm",
    "terraform",
    "skaffold",
    "cpp",
]

_K8S_RESOURCE_TYPES = {
    "Deployment",
    "Service",
    "StatefulSet",
    "ConfigMap",
    "Secret",
    "DaemonSet",
    "ReplicaSet",
    "Job",
    "CronJob",
    "Ingress",
    "Pod",
    "PersistentVolumeClaim",
    "PersistentVolume",
    "ServiceAccount",
    "Namespace",
    "HorizontalPodAutoscaler",
}


def _safe_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def _safe_is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _safe_glob(base: Path, pattern: str) -> list[Path]:
    try:
        return list(base.glob(pattern))
    except OSError:
        return []


# Directories detection never descends into: the always-skipped set (VCS
# metadata, virtualenvs, caches, node_modules) plus build output.  Any
# directory whose name starts with "." is pruned as well, matching the AST
# collectors' hidden-directory rule.
_PRUNED_DIR_NAMES: frozenset[str] = ALWAYS_SKIP_DIRS | {"target"}


def _is_pruned_dir(name: str, rel_dir: str) -> bool:
    """Return True if the directory *name* at *rel_dir* must not be walked."""
    return (
        name.startswith(".") or name in _PRUNED_DIR_NAMES or should_exclude_path(f"{rel_dir}/")
    )


def _safe_rglob(base: Path, pattern: str) -> list[Path]:
    """Return paths under *base* whose name matches the glob *pattern*.

    Matches what ``base.rglob(pattern)`` returns for a single-component
    pattern, minus excluded paths, but prunes hidden, always-skipped,
    ``target`` and test directories during the walk so they are never listed.
    Unreadable directories are skipped; any other ``OSError`` yields ``[]``.
    """
    matches: list[Path] = []
    try:
        for dirpath, dirnames, filenames in os.walk(base):
            current = Path(dirpath)
            rel = current.relative_to(base).as_posix()
            prefix = "" if rel == "." else f"{rel}/"
            dirnames[:] = sorted(d for d in dirnames if not _is_pruned_dir(d, f"{prefix}{d}"))
            for name in (*dirnames, *sorted(filenames)):
                if fnmatch.fnmatch(name, pattern) and not should_exclude_path(
                    f"{prefix}{name}"
                ):
                    matches.append(current / name)
    except OSError:
        return []
    return matches


_JAVA_BUILD_FILES = ("pom.xml", "build.gradle", "build.gradle.kts")


def _detect_java(repo: Path) -> bool:
    for name in _JAVA_BUILD_FILES:
        if _safe_exists(repo / name):
            return True
    # Monorepos commonly nest Java modules in subdirectories.
    for name in _JAVA_BUILD_FILES:
        if _safe_rglob(repo, name):
            return True
    return bool(_safe_rglob(repo, "*.java"))


def _detect_spring_boot(repo: Path) -> bool:
    for name in ("application.yml", "application.yaml", "application.properties"):
        for path in _safe_rglob(repo, name):
            if path.parent.as_posix().endswith("src/main/resources"):
                return True
    for name in _JAVA_BUILD_FILES:
        for path in _safe_rglob(repo, name):
            content = _safe_read_text(path)
            if content and "spring-boot" in content:
                return True
    return False


def _detect_kubernetes(repo: Path) -> bool:
    if _safe_rglob(repo, "kustomization.yaml"):
        return True
    for prefix in ("k8s", "kubernetes", "kubernetes-manifests", "deploy", "manifests"):
        d = repo / prefix
        if not _safe_is_dir(d):
            continue
        for ext in ("**/*.yaml", "**/*.yml"):
            for f in _safe_glob(d, ext):
                content = _safe_read_text(f)
                if content:
                    for kind in _K8S_RESOURCE_TYPES:
                        if f"kind: {kind}" in content or f"kind:{kind}" in content:
                            return True
    return False


def _detect_apim(repo: Path) -> bool:
    for f in _safe_rglob(repo, "*.xml"):
        content = _safe_read_text(f)
        if content and "<policies>" in content:
            if any(
                tag in content
                for tag in (
                    "<inbound>",
                    "<inbound/>",
                    "<backend>",
                    "<backend/>",
                    "<outbound>",
                    "<outbound/>",
                )
            ):
                return True
    return False


def _detect_ci(repo: Path) -> bool:
    workflows = repo / ".github" / "workflows"
    if _safe_is_dir(workflows):
        if _safe_glob(workflows, "*.yml") or _safe_glob(workflows, "*.yaml"):
            return True
    for name in (".gitlab-ci.yml", "Jenkinsfile", "azure-pipelines.yml"):
        if _safe_exists(repo / name):
            return True
    return False


def _detect_adr(repo: Path) -> bool:
    for prefix in ("docs/adr", "doc/adr", "adr"):
        d = repo / prefix
        if _safe_is_dir(d) and _safe_glob(d, "*.md"):
            return True
    return False


def _detect_dockerfile(repo: Path) -> bool:
    if _safe_exists(repo / "Dockerfile"):
        return True
    for name in ("docker-compose.yml", "docker-compose.yaml"):
        if _safe_exists(repo / name):
            return True
    if _safe_rglob(repo, "*.Dockerfile"):
        return True
    if _safe_rglob(repo, "Dockerfile"):
        return True
    if _safe_rglob(repo, "dockerfile"):
        return True
    return False


def _detect_grpc(repo: Path) -> bool:
    return bool(_safe_rglob(repo, "*.proto"))


def _detect_go(repo: Path) -> bool:
    if _safe_exists(repo / "go.mod"):
        return True
    return bool(_safe_rglob(repo, "go.mod"))


def _detect_rust(repo: Path) -> bool:
    if _safe_exists(repo / "Cargo.toml"):
        return True
    return bool(_safe_rglob(repo, "Cargo.toml"))


def _detect_python(repo: Path) -> bool:
    for name in ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt"):
        if _safe_exists(repo / name):
            return True
    for pattern in ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt"):
        if _safe_rglob(repo, pattern):
            return True
    # Script-only repos (no packaging manifest) still contain Python source.
    return bool(_safe_rglob(repo, "*.py"))


def _detect_nodejs(repo: Path) -> bool:
    if _safe_exists(repo / "package.json"):
        return True
    return bool(_safe_rglob(repo, "package.json"))


def _detect_csharp(repo: Path) -> bool:
    if _safe_rglob(repo, "*.csproj"):
        return True
    return bool(_safe_rglob(repo, "*.sln"))


def _detect_istio(repo: Path) -> bool:
    if _safe_is_dir(repo / "istio"):
        return True
    for f in _safe_rglob(repo, "*.yaml"):
        content = _safe_read_text(f)
        if content and (
            "kind: VirtualService" in content or "kind: DestinationRule" in content
        ):
            return True
    return False


def _detect_otel(repo: Path) -> bool:
    dep_files = ("pom.xml", "go.mod", "package.json", "requirements.txt", "pyproject.toml")
    for name in dep_files:
        content = _safe_read_text(repo / name)
        if content and "opentelemetry" in content:
            return True
    for pattern in ("*otel*collector*config*", "*otelcol*"):
        for f in _safe_rglob(repo, pattern):
            if f.suffix in (".yaml", ".yml"):
                return True
    return False


def _detect_helm(repo: Path) -> bool:
    return bool(_safe_rglob(repo, "Chart.yaml"))


def _detect_terraform(repo: Path) -> bool:
    return bool(_safe_rglob(repo, "*.tf"))


def _detect_skaffold(repo: Path) -> bool:
    return bool(_safe_rglob(repo, "skaffold.yaml"))


def _detect_cpp(repo: Path) -> bool:
    for name in ("CMakeLists.txt", "Makefile", "meson.build"):
        if _safe_exists(repo / name):
            return True
    for pattern in ("*.vcxproj", "conanfile.txt", "conanfile.py", "vcpkg.json"):
        if _safe_rglob(repo, pattern):
            return True
    for ext in ("*.cpp", "*.cc", "*.cxx"):
        if _safe_rglob(repo, ext):
            return True
    return False


_DETECTORS: dict[str, Callable[..., bool]] = {
    "java": _detect_java,
    "spring_boot": _detect_spring_boot,
    "kubernetes": _detect_kubernetes,
    "apim": _detect_apim,
    "ci": _detect_ci,
    "adr": _detect_adr,
    "dockerfile": _detect_dockerfile,
    "grpc": _detect_grpc,
    "go": _detect_go,
    "rust": _detect_rust,
    "python": _detect_python,
    "nodejs": _detect_nodejs,
    "csharp": _detect_csharp,
    "istio": _detect_istio,
    "otel": _detect_otel,
    "helm": _detect_helm,
    "terraform": _detect_terraform,
    "skaffold": _detect_skaffold,
    "cpp": _detect_cpp,
}


def detect_technologies(repo_path: Path) -> dict[str, bool]:
    """Detect which technologies are present in a repository.

    Scans file structure and dependency manifests to identify technologies.
    Returns a dict with all technology keys, each mapped to True/False.
    Detection failures for individual technologies are silently skipped.
    """
    logger.info("Detecting technologies in %s", repo_path)
    result: dict[str, bool] = {}
    for key in ALL_TECH_KEYS:
        try:
            result[key] = _DETECTORS[key](repo_path)
        except Exception as e:  # noqa: BLE001
            logger.debug("Detector '%s' failed for %s: %s", key, repo_path, e)
            result[key] = False
    detected = [k for k, v in result.items() if v]
    logger.info("Technologies detected: %s", ", ".join(detected) if detected else "(none)")
    return result


__all__ = ["ALL_TECH_KEYS", "detect_technologies"]
