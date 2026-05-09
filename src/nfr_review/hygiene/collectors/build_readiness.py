"""Build readiness collector — checks for build system, version strategy,
and entry point configuration in Python packages.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

from nfr_review.hygiene import hygiene_collector_registry
from nfr_review.models import Evidence


def _parse_pyproject(repo_path: Path) -> dict[str, Any] | None:
    pp = repo_path / "pyproject.toml"
    if not pp.is_file():
        return None
    try:
        return tomllib.loads(pp.read_text(encoding="utf-8"))
    except Exception:
        return None


def _detect_build_system(repo_path: Path, pyproject: dict[str, Any] | None) -> dict[str, Any]:
    if pyproject and "build-system" in pyproject:
        backend = pyproject["build-system"].get("build-backend", "unknown")
        return {"has_build_system": True, "backend": backend, "path": "pyproject.toml"}

    if (repo_path / "setup.py").is_file():
        return {
            "has_build_system": True,
            "backend": "setuptools (setup.py)",
            "path": "setup.py",
        }

    if (repo_path / "setup.cfg").is_file():
        return {
            "has_build_system": True,
            "backend": "setuptools (setup.cfg)",
            "path": "setup.cfg",
        }

    return {"has_build_system": False, "backend": None, "path": None}


_VERSION_RE = re.compile(r'__version__\s*=\s*["\']([^"\']+)["\']')


def _detect_version(repo_path: Path, pyproject: dict[str, Any] | None) -> dict[str, Any]:
    if pyproject:
        project = pyproject.get("project", {})
        if "version" in project:
            return {"declared": True, "value": project["version"], "source": "pyproject.toml"}

        dynamic = project.get("dynamic", [])
        if "version" in dynamic:
            return {
                "declared": True,
                "value": "(dynamic)",
                "source": "pyproject.toml[dynamic]",
            }

    for setup_file in ("setup.py", "setup.cfg"):
        p = repo_path / setup_file
        if p.is_file():
            try:
                text = p.read_text(encoding="utf-8")
            except Exception:  # nosec B112
                continue
            m = re.search(r'version\s*=\s*["\']?([^"\'\s,\n]+)["\']?', text)
            if m:
                return {"declared": True, "value": m.group(1), "source": setup_file}

    for init_path in repo_path.glob("src/*/__init__.py"):
        try:
            text = init_path.read_text(encoding="utf-8")
        except Exception:  # nosec B112
            continue
        m = _VERSION_RE.search(text)
        if m:
            rel = str(init_path.relative_to(repo_path))
            return {"declared": True, "value": m.group(1), "source": rel}

    for init_path in repo_path.glob("*/__init__.py"):
        if init_path.parent.name.startswith(".") or init_path.parent.name == "tests":
            continue
        try:
            text = init_path.read_text(encoding="utf-8")
        except Exception:  # nosec B112
            continue
        m = _VERSION_RE.search(text)
        if m:
            rel = str(init_path.relative_to(repo_path))
            return {"declared": True, "value": m.group(1), "source": rel}

    return {"declared": False, "value": None, "source": None}


def _detect_entry_points(repo_path: Path, pyproject: dict[str, Any] | None) -> dict[str, Any]:
    if pyproject:
        project = pyproject.get("project", {})
        scripts = project.get("scripts", {})
        gui_scripts = project.get("gui-scripts", {})
        all_scripts = {**scripts, **gui_scripts}
        if all_scripts:
            return {"has_entry_points": True, "scripts": all_scripts}

    for setup_file in ("setup.py", "setup.cfg"):
        p = repo_path / setup_file
        if p.is_file():
            try:
                text = p.read_text(encoding="utf-8")
            except Exception:  # nosec B112
                continue
            if "console_scripts" in text or "gui_scripts" in text:
                label = f"(parsed from {setup_file})"
                return {
                    "has_entry_points": True,
                    "scripts": {label: "..."},
                }

    return {"has_entry_points": False, "scripts": {}}


class BuildReadinessCollector:
    name = "build-readiness"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        pyproject = _parse_pyproject(repo_path)

        payload: dict[str, Any] = {
            "build_system": _detect_build_system(repo_path, pyproject),
            "version": _detect_version(repo_path, pyproject),
            "entry_points": _detect_entry_points(repo_path, pyproject),
        }

        return [
            Evidence(
                collector_name=self.name,
                collector_version=self.version,
                locator=".",
                kind="build-readiness-analysis",
                payload=payload,
            )
        ]


def _register() -> None:
    if "build-readiness" not in hygiene_collector_registry:
        hygiene_collector_registry.register("build-readiness", BuildReadinessCollector())


_register()

__all__ = ["BuildReadinessCollector"]
