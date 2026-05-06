"""Auto-detect technologies present in a repository."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

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
    "python",
    "nodejs",
    "csharp",
    "istio",
    "otel",
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


def _safe_read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return None


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


def _safe_rglob(base: Path, pattern: str) -> list[Path]:
    try:
        return list(base.rglob(pattern))
    except OSError:
        return []


def _detect_java(repo: Path) -> bool:
    for name in ("pom.xml", "build.gradle", "build.gradle.kts"):
        if _safe_exists(repo / name):
            return True
    if _safe_glob(repo / "src", "**/*.java"):
        return True
    return False


def _detect_spring_boot(repo: Path) -> bool:
    resources = repo / "src" / "main" / "resources"
    if _safe_is_dir(resources):
        for name in ("application.yml", "application.properties"):
            if _safe_exists(resources / name):
                return True
    for name in ("pom.xml", "build.gradle", "build.gradle.kts"):
        content = _safe_read_text(repo / name)
        if content and "spring-boot" in content:
            return True
    return False


def _detect_kubernetes(repo: Path) -> bool:
    if _safe_exists(repo / "kustomization.yaml"):
        return True
    for prefix in ("k8s", "kubernetes"):
        for f in _safe_glob(repo / prefix, "**/*.yaml"):
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
    return _safe_exists(repo / "go.mod")


def _detect_python(repo: Path) -> bool:
    for name in ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt"):
        if _safe_exists(repo / name):
            return True
    return False


def _detect_nodejs(repo: Path) -> bool:
    return _safe_exists(repo / "package.json")


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
    "python": _detect_python,
    "nodejs": _detect_nodejs,
    "csharp": _detect_csharp,
    "istio": _detect_istio,
    "otel": _detect_otel,
}


def detect_technologies(repo_path: Path) -> dict[str, bool]:
    """Detect which technologies are present in a repository.

    Scans file structure and dependency manifests to identify technologies.
    Returns a dict with all 14 technology keys, each mapped to True/False.
    Detection failures for individual technologies are silently skipped.
    """
    result: dict[str, bool] = {}
    for key in ALL_TECH_KEYS:
        try:
            result[key] = _DETECTORS[key](repo_path)
        except Exception:
            result[key] = False
    return result


__all__ = ["ALL_TECH_KEYS", "detect_technologies"]
