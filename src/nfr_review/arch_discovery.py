# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Component and boundary discovery for architecture documentation.

Scans repository structure, build configs, deployment manifests, and
dependency files to identify major architectural components and their
boundaries. Operates without LLM — pure structural inference.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ruamel.yaml import YAML, YAMLError

from nfr_review.arch_models import Component, ComponentBoundary, TechStackEntry
from nfr_review.path_filter import should_exclude_path

logger = logging.getLogger(__name__)

ComponentType = Literal[
    "service", "library", "database", "queue", "gateway", "ui", "worker", "external"
]

_HIDDEN_DIRS = frozenset(
    {
        ".git",
        ".svn",
        ".hg",
        ".idea",
        ".vscode",
        ".gsd",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
        "target",
        "build",
        "dist",
        ".gradle",
    }
)

_MONOREPO_DIRS = frozenset(
    {"packages", "apps", "services", "modules", "libs", "crates", "cmd", "internal"}
)

_BUILD_FILES = frozenset(
    {
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "package.json",
        "pyproject.toml",
        "setup.py",
        "Cargo.toml",
        "go.mod",
        "CMakeLists.txt",
    }
)


def _safe_read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return None


def _safe_yaml_load(text: str) -> Any:
    _yaml = YAML(typ="safe")
    try:
        return _yaml.load(text)
    except YAMLError:
        return None


def _safe_yaml_load_all(text: str) -> list[Any]:
    _yaml = YAML(typ="safe")
    try:
        return [doc for doc in _yaml.load_all(text) if doc is not None]
    except YAMLError:
        return []


def _make_id(prefix: str, name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    short_hash = hashlib.sha256(name.encode()).hexdigest()[:6]
    return f"{prefix}-{slug}-{short_hash}"


_ML_FRAMEWORK_MARKERS: dict[str, tuple[str, str]] = {
    "torch": ("PyTorch", "framework"),
    "pytorch": ("PyTorch", "framework"),
    "tensorflow": ("TensorFlow", "framework"),
    "keras": ("Keras", "framework"),
    "sklearn": ("scikit-learn", "library"),
    "scikit-learn": ("scikit-learn", "library"),
    "onnx": ("ONNX", "library"),
    "onnxruntime": ("ONNX Runtime", "library"),
    "xgboost": ("XGBoost", "library"),
    "lightgbm": ("LightGBM", "library"),
    "jax": ("JAX", "framework"),
}


def _detect_ml_frameworks(path: Path, entries: list[TechStackEntry]) -> None:
    """Scan requirements.txt / pyproject.toml for ML framework dependencies."""
    seen: set[str] = {e.name for e in entries}
    req_file = path / "requirements.txt"
    if req_file.is_file():
        content = _safe_read_text(req_file) or ""
        for line in content.splitlines():
            pkg = line.strip().split("=")[0].split(">")[0].split("<")[0].split("[")[0].strip()
            pkg_lower = pkg.lower()
            if pkg_lower in _ML_FRAMEWORK_MARKERS:
                name, role = _ML_FRAMEWORK_MARKERS[pkg_lower]
                if name not in seen:
                    entries.append(TechStackEntry(name=name, role=role))
                    seen.add(name)


def _infer_tech_stack(path: Path) -> list[TechStackEntry]:
    """Infer the tech stack for a single component directory."""
    entries: list[TechStackEntry] = []

    if (path / "pom.xml").is_file():
        entries.append(TechStackEntry(name="Java", role="language"))
        content = _safe_read_text(path / "pom.xml")
        if content and "spring-boot" in content:
            entries.append(TechStackEntry(name="Spring Boot", role="framework"))
    elif (path / "build.gradle").is_file() or (path / "build.gradle.kts").is_file():
        entries.append(TechStackEntry(name="Java", role="language"))
        gradle_file = path / "build.gradle"
        if not gradle_file.is_file():
            gradle_file = path / "build.gradle.kts"
        content = _safe_read_text(gradle_file)
        if content and "spring" in content.lower():
            entries.append(TechStackEntry(name="Spring Boot", role="framework"))

    if (path / "package.json").is_file():
        entries.append(TechStackEntry(name="Node.js", role="runtime"))
        content = _safe_read_text(path / "package.json")
        if content:
            if '"react"' in content:
                entries.append(TechStackEntry(name="React", role="framework"))
            if '"next"' in content or '"next"' in content:
                entries.append(TechStackEntry(name="Next.js", role="framework"))
            if '"express"' in content:
                entries.append(TechStackEntry(name="Express", role="framework"))

    _python_build = (
        (path / "pyproject.toml").is_file()
        or (path / "setup.py").is_file()
        or (path / "setup.cfg").is_file()
        or (path / "requirements.txt").is_file()
    )
    if _python_build:
        entries.append(TechStackEntry(name="Python", role="language"))
        content = _safe_read_text(path / "pyproject.toml") or ""
        if "fastapi" in content.lower():
            entries.append(TechStackEntry(name="FastAPI", role="framework"))
        elif "django" in content.lower():
            entries.append(TechStackEntry(name="Django", role="framework"))
        elif "flask" in content.lower():
            entries.append(TechStackEntry(name="Flask", role="framework"))
        _detect_ml_frameworks(path, entries)

    if (path / "go.mod").is_file():
        entries.append(TechStackEntry(name="Go", role="language"))

    if (path / "Cargo.toml").is_file():
        entries.append(TechStackEntry(name="Rust", role="language"))

    if (path / "CMakeLists.txt").is_file():
        entries.append(TechStackEntry(name="C++", role="language"))
        cmake_content = _safe_read_text(path / "CMakeLists.txt") or ""
        cmake_lower = cmake_content.lower()
        if "juce_add_plugin" in cmake_lower or "juce_add_gui_app" in cmake_lower:
            entries.append(TechStackEntry(name="JUCE", role="framework"))
        if (
            "vst3sdk" in cmake_lower
            or "vst3_sdk" in cmake_lower
            or "smtg_add_vst3plugin" in cmake_lower
        ):
            entries.append(TechStackEntry(name="VST3 SDK", role="framework"))
        if "onnxruntime" in cmake_lower:
            entries.append(TechStackEntry(name="ONNX Runtime", role="library"))

    if (path / "dvc.yaml").is_file() or (path / "dvc.lock").is_file():
        entries.append(TechStackEntry(name="DVC", role="tool"))

    return entries


def _infer_component_type(
    name: str, path: Path, tech_stack: list[TechStackEntry]
) -> ComponentType:
    """Infer the component type from naming and structure."""
    name_lower = name.lower()

    if any(
        kw in name_lower for kw in ("db", "database", "postgres", "mysql", "mongo", "redis")
    ):
        return "database"

    if any(kw in name_lower for kw in ("queue", "kafka", "rabbit", "nats", "pubsub")):
        return "queue"

    if any(kw in name_lower for kw in ("gateway", "proxy", "ingress", "nginx", "envoy")):
        return "gateway"

    if any(kw in name_lower for kw in ("ui", "frontend", "web", "client", "dashboard", "app")):
        has_react = any(t.name == "React" for t in tech_stack)
        has_nextjs = any(t.name == "Next.js" for t in tech_stack)
        if has_react or has_nextjs:
            return "ui"

    if any(kw in name_lower for kw in ("worker", "consumer", "processor", "job")):
        return "worker"

    if any(kw in name_lower for kw in ("lib", "common", "shared", "util", "sdk")):
        return "library"

    return "service"


def _discover_monorepo_components(
    repo_path: Path, repo_name: str | None = None
) -> list[Component]:
    """Discover components from monorepo directory structures."""
    components: list[Component] = []
    effective_name = repo_name or repo_path.name

    for mono_dir_name in _MONOREPO_DIRS:
        mono_dir = repo_path / mono_dir_name
        if not mono_dir.is_dir():
            continue

        for child in sorted(mono_dir.iterdir()):
            if not child.is_dir():
                continue
            if child.name.startswith(".") or child.name in _HIDDEN_DIRS:
                continue

            has_build = any((child / bf).is_file() for bf in _BUILD_FILES)
            has_src = any((child / sd).is_dir() for sd in ("src", "lib", "app", "cmd", "main"))

            if not has_build and not has_src:
                continue

            tech = _infer_tech_stack(child)
            comp_type = _infer_component_type(child.name, child, tech)
            comp_id = _make_id("comp", f"{effective_name}/{child.name}")

            components.append(
                Component(
                    id=comp_id,
                    name=child.name,
                    description=f"Component in {mono_dir_name}/ directory",
                    component_type=comp_type,
                    boundaries=[
                        ComponentBoundary(
                            boundary_type="directory",
                            path=str(child.relative_to(repo_path)),
                            repo=effective_name,
                        )
                    ],
                    tech_stack=tech,
                    repo=effective_name,
                )
            )

    return components


def _discover_k8s_components(repo_path: Path, repo_name: str | None = None) -> list[Component]:
    """Discover components from Kubernetes manifests."""
    components: list[Component] = []
    effective_name = repo_name or repo_path.name
    seen_names: set[str] = set()

    k8s_dirs = ["k8s", "kubernetes", "deploy", "manifests", "helm"]
    search_dirs = [repo_path / d for d in k8s_dirs if (repo_path / d).is_dir()]
    search_dirs.append(repo_path)

    for search_dir in search_dirs:
        try:
            yaml_files = list(search_dir.rglob("*.yaml")) + list(search_dir.rglob("*.yml"))
        except OSError:
            continue

        for yaml_file in yaml_files:
            rel_path = str(yaml_file.relative_to(repo_path))
            if should_exclude_path(rel_path):
                continue

            content = _safe_read_text(yaml_file)
            if not content:
                continue

            docs = _safe_yaml_load_all(content)
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                kind = doc.get("kind", "")
                if kind not in ("Deployment", "StatefulSet", "DaemonSet", "Service"):
                    continue

                metadata = doc.get("metadata", {})
                if not isinstance(metadata, dict):
                    continue
                name = metadata.get("name", "")
                if not name or name in seen_names:
                    continue
                seen_names.add(name)

                if kind == "Service":
                    continue

                comp_id = _make_id("k8s", f"{effective_name}/{name}")
                comp_type: ComponentType = "worker" if kind == "DaemonSet" else "service"

                labels = metadata.get("labels", {}) or {}
                tech: list[TechStackEntry] = []

                spec = doc.get("spec", {}) or {}
                template = spec.get("template", {}) or {}
                pod_spec = template.get("spec", {}) or {}
                containers = pod_spec.get("containers", []) or []

                for container in containers:
                    if isinstance(container, dict):
                        image = container.get("image", "")
                        if image:
                            tech.append(
                                TechStackEntry(
                                    name=image.split(":")[0].split("/")[-1],
                                    version=image.split(":")[-1] if ":" in image else None,
                                    role="container-image",
                                )
                            )

                components.append(
                    Component(
                        id=comp_id,
                        name=name,
                        description=f"Kubernetes {kind} workload",
                        component_type=comp_type,
                        boundaries=[
                            ComponentBoundary(
                                boundary_type="build_target",
                                path=rel_path,
                                repo=effective_name,
                            )
                        ],
                        tech_stack=tech,
                        repo=effective_name,
                        responsibilities=[f"{labels.get('app.kubernetes.io/component', '')}"]
                        if labels.get("app.kubernetes.io/component")
                        else [],
                    )
                )

    return components


def _discover_docker_compose_components(
    repo_path: Path, repo_name: str | None = None
) -> list[Component]:
    """Discover components from docker-compose files."""
    components: list[Component] = []
    effective_name = repo_name or repo_path.name

    compose_names = [
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
    ]

    for compose_name in compose_names:
        compose_file = repo_path / compose_name
        if not compose_file.is_file():
            continue

        content = _safe_read_text(compose_file)
        if not content:
            continue

        data = _safe_yaml_load(content)
        if not isinstance(data, dict):
            continue

        services = data.get("services", {})
        if not isinstance(services, dict):
            continue

        for svc_name, svc_config in services.items():
            if not isinstance(svc_config, dict):
                continue

            comp_id = _make_id("compose", f"{effective_name}/{svc_name}")
            tech: list[TechStackEntry] = []

            image = svc_config.get("image", "")
            if image:
                tech.append(
                    TechStackEntry(
                        name=image.split(":")[0].split("/")[-1],
                        version=image.split(":")[-1] if ":" in image else None,
                        role="container-image",
                    )
                )

            build_ctx = svc_config.get("build", "")
            boundary_path = compose_name
            if isinstance(build_ctx, str) and build_ctx:
                boundary_path = build_ctx
            elif isinstance(build_ctx, dict) and build_ctx.get("context"):
                boundary_path = build_ctx["context"]

            comp_type = _infer_component_type(svc_name, repo_path, tech)

            components.append(
                Component(
                    id=comp_id,
                    name=svc_name,
                    description="Docker Compose service",
                    component_type=comp_type,
                    boundaries=[
                        ComponentBoundary(
                            boundary_type="build_target",
                            path=boundary_path,
                            repo=effective_name,
                        )
                    ],
                    tech_stack=tech,
                    repo=effective_name,
                )
            )

        break  # Only process first compose file found

    return components


_SOURCE_DIRS = frozenset({"source", "src"})

_CPP_EXTENSIONS = frozenset({".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".hxx"})

_SOURCE_SUBDIR_SKIP = frozenset(
    {
        "build",
        "build-test",
        "test",
        "tests",
        "third_party",
        "thirdparty",
        "vendor",
        "external",
        "cmake",
        "resource",
        "resources",
        "docs",
        "doc",
    }
)

_SUBDIR_TYPE_HINTS: dict[str, ComponentType] = {
    "ml": "worker",
    "inference": "worker",
    "training": "worker",
    "transforms": "library",
    "transform": "library",
    "evolution": "library",
    "ui": "ui",
    "gui": "ui",
    "editor": "ui",
    "view": "ui",
    "core": "library",
    "common": "library",
    "utils": "library",
    "net": "library",
    "network": "library",
    "audio": "library",
    "dsp": "library",
}

_MIN_SOURCE_FILES = 2


def _discover_source_subdirectories(
    repo_path: Path, repo_name: str | None = None
) -> list[Component]:
    """Discover sub-components from C++ source directory structure.

    Scans source/ or src/ for subdirectories containing enough source files
    to qualify as distinct architectural components (e.g. ml/, transforms/).
    """
    components: list[Component] = []
    effective_name = repo_name or repo_path.name

    for source_dir_name in _SOURCE_DIRS:
        source_dir = repo_path / source_dir_name
        if not source_dir.is_dir():
            continue

        for child in sorted(source_dir.iterdir()):
            if not child.is_dir():
                continue
            if child.name.startswith(".") or child.name.lower() in _SOURCE_SUBDIR_SKIP:
                continue

            src_files = [
                f for f in child.iterdir() if f.is_file() and f.suffix in _CPP_EXTENSIONS
            ]
            if len(src_files) < _MIN_SOURCE_FILES:
                continue

            comp_type = _SUBDIR_TYPE_HINTS.get(child.name.lower(), "library")
            rel_path = str(child.relative_to(repo_path))
            comp_id = _make_id("src", f"{effective_name}/{rel_path}")

            components.append(
                Component(
                    id=comp_id,
                    name=child.name,
                    description=f"C++ source sub-component in {source_dir_name}/",
                    component_type=comp_type,
                    boundaries=[
                        ComponentBoundary(
                            boundary_type="directory",
                            path=rel_path,
                            repo=effective_name,
                        )
                    ],
                    tech_stack=[TechStackEntry(name="C++", role="language")],
                    repo=effective_name,
                )
            )

        if components:
            logger.debug(
                "Found %d source sub-components in %s/", len(components), source_dir_name
            )

    return components


def _discover_ml_pipeline_components(
    repo_path: Path, repo_name: str | None = None
) -> list[Component]:
    """Discover ML training pipeline directories.

    Detects directories containing requirements.txt + Python scripts as
    ML pipeline components. Parses requirements.txt for ML framework
    identification.
    """
    components: list[Component] = []
    effective_name = repo_name or repo_path.name

    for child in sorted(repo_path.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith(".") or child.name in _HIDDEN_DIRS:
            continue

        req_file = child / "requirements.txt"
        if not req_file.is_file():
            continue

        py_files = list(child.rglob("*.py"))
        if len(py_files) < 2:
            continue

        tech = _infer_tech_stack(child)
        has_dvc = (child / "dvc.yaml").is_file() or (repo_path / "dvc.yaml").is_file()
        if has_dvc and not any(t.name == "DVC" for t in tech):
            tech.append(TechStackEntry(name="DVC", role="tool"))

        rel_path = str(child.relative_to(repo_path))
        comp_id = _make_id("ml", f"{effective_name}/{rel_path}")

        desc = "ML training pipeline"
        ml_names = [t.name for t in tech if t.role == "framework" and t.name != "Python"]
        if ml_names:
            desc = f"ML training pipeline ({', '.join(ml_names)})"

        components.append(
            Component(
                id=comp_id,
                name=child.name,
                description=desc,
                component_type="worker",
                boundaries=[
                    ComponentBoundary(
                        boundary_type="directory",
                        path=rel_path,
                        repo=effective_name,
                    )
                ],
                tech_stack=tech,
                repo=effective_name,
            )
        )

    if components:
        logger.debug("Found %d ML pipeline components", len(components))

    return components


def _discover_nested_build_components(
    repo_path: Path, repo_name: str | None = None
) -> list[Component]:
    """Discover subdirectories with their own build files.

    Finds non-standard nested project directories (outside _MONOREPO_DIRS)
    that have build configuration, indicating a separate component.
    """
    components: list[Component] = []
    effective_name = repo_name or repo_path.name

    for child in sorted(repo_path.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith(".") or child.name in _HIDDEN_DIRS:
            continue
        if child.name.lower() in _MONOREPO_DIRS:
            continue
        if child.name.lower() in _SOURCE_SUBDIR_SKIP:
            continue

        has_build = any((child / bf).is_file() for bf in _BUILD_FILES)
        if not has_build:
            continue

        tech = _infer_tech_stack(child)
        comp_type = _infer_component_type(child.name, child, tech)
        rel_path = str(child.relative_to(repo_path))
        comp_id = _make_id("nested", f"{effective_name}/{rel_path}")

        components.append(
            Component(
                id=comp_id,
                name=child.name,
                description="Nested project component",
                component_type=comp_type,
                boundaries=[
                    ComponentBoundary(
                        boundary_type="directory",
                        path=rel_path,
                        repo=effective_name,
                    )
                ],
                tech_stack=tech,
                repo=effective_name,
            )
        )

    if components:
        logger.debug("Found %d nested build components", len(components))

    return components


def _discover_build_root_component(
    repo_path: Path, repo_name: str | None = None
) -> Component | None:
    """If the repo itself is a single-component project, return it."""
    effective_name = repo_name or repo_path.name
    build_files_present = [bf for bf in _BUILD_FILES if (repo_path / bf).is_file()]

    if not build_files_present:
        return None

    tech = _infer_tech_stack(repo_path)
    comp_type = _infer_component_type(effective_name, repo_path, tech)
    comp_id = _make_id("comp", effective_name)

    return Component(
        id=comp_id,
        name=effective_name,
        description="Root project component",
        component_type=comp_type,
        boundaries=[
            ComponentBoundary(
                boundary_type="repo",
                path=".",
                repo=effective_name,
            )
        ],
        tech_stack=tech,
        repo=effective_name,
    )


def _discover_multi_module_maven(
    repo_path: Path, repo_name: str | None = None
) -> list[Component]:
    """Discover sub-modules from a Maven multi-module project."""
    components: list[Component] = []
    effective_name = repo_name or repo_path.name

    root_pom = repo_path / "pom.xml"
    if not root_pom.is_file():
        return []

    content = _safe_read_text(root_pom)
    if not content:
        return []

    module_pattern = re.compile(r"<module>([^<]+)</module>")
    modules = module_pattern.findall(content)

    for module_name in modules:
        module_path = repo_path / module_name
        if not module_path.is_dir():
            continue
        if not (module_path / "pom.xml").is_file():
            continue

        tech = _infer_tech_stack(module_path)
        comp_type = _infer_component_type(module_name, module_path, tech)
        comp_id = _make_id("maven", f"{effective_name}/{module_name}")

        components.append(
            Component(
                id=comp_id,
                name=module_name,
                description="Maven module",
                component_type=comp_type,
                boundaries=[
                    ComponentBoundary(
                        boundary_type="module",
                        path=module_name,
                        repo=effective_name,
                    )
                ],
                tech_stack=tech,
                repo=effective_name,
            )
        )

    return components


def _discover_gradle_subprojects(
    repo_path: Path, repo_name: str | None = None
) -> list[Component]:
    """Discover sub-projects from a Gradle settings file."""
    components: list[Component] = []
    effective_name = repo_name or repo_path.name

    for settings_name in ("settings.gradle", "settings.gradle.kts"):
        settings_file = repo_path / settings_name
        if not settings_file.is_file():
            continue

        content = _safe_read_text(settings_file)
        if not content:
            continue

        include_pattern = re.compile(r"include\s*[('\"]([^'\"]+)['\"]")
        for match in include_pattern.finditer(content):
            project_name = match.group(1).lstrip(":")
            project_path = repo_path / project_name.replace(":", "/")
            if not project_path.is_dir():
                continue

            tech = _infer_tech_stack(project_path)
            comp_type = _infer_component_type(project_name, project_path, tech)
            comp_id = _make_id("gradle", f"{effective_name}/{project_name}")

            components.append(
                Component(
                    id=comp_id,
                    name=project_name,
                    description="Gradle sub-project",
                    component_type=comp_type,
                    boundaries=[
                        ComponentBoundary(
                            boundary_type="module",
                            path=project_name.replace(":", "/"),
                            repo=effective_name,
                        )
                    ],
                    tech_stack=tech,
                    repo=effective_name,
                )
            )

        break

    return components


def _discover_java_base_package(component_path: Path) -> str | None:
    """Walk src/main/{java,kotlin}/ to find the base Java/Kotlin package."""
    for lang_dir in ("java", "kotlin"):
        src = component_path / "src" / "main" / lang_dir
        if not src.is_dir():
            continue

        current = src
        parts: list[str] = []

        while True:
            try:
                subdirs = sorted(
                    d for d in current.iterdir() if d.is_dir() and not d.name.startswith(".")
                )
            except OSError:
                break

            has_source = any(
                f.suffix in (".java", ".kt") for f in current.iterdir() if f.is_file()
            )

            if len(subdirs) == 1 and not has_source:
                parts.append(subdirs[0].name)
                current = subdirs[0]
            else:
                break

        if parts:
            return ".".join(parts)

    return None


def _discover_python_top_package(component_path: Path) -> str | None:
    """Find the top-level Python package in a component directory."""
    for root in (component_path / "src", component_path):
        if not root.is_dir():
            continue
        try:
            children = sorted(root.iterdir())
        except OSError:
            continue
        for child in children:
            if (
                child.is_dir()
                and not child.name.startswith(".")
                and child.name not in _HIDDEN_DIRS
                and (child / "__init__.py").is_file()
            ):
                return child.name
    return None


def _discover_go_module_path(component_path: Path) -> str | None:
    """Read go.mod for the module path."""
    go_mod = component_path / "go.mod"
    if not go_mod.is_file():
        return None
    content = _safe_read_text(go_mod)
    if not content:
        return None
    match = re.search(r"^module\s+(\S+)", content, re.MULTILINE)
    return match.group(1) if match else None


def _enrich_package_boundaries(
    components: list[Component],
    repo_path: Path,
) -> None:
    """Add package-type boundaries to components where source packages are found."""
    for comp in components:
        if not comp.boundaries:
            continue

        primary = comp.boundaries[0]
        comp_path = repo_path / primary.path if primary.path not in (".", "") else repo_path

        if not comp_path.is_dir():
            continue

        pkg = (
            _discover_java_base_package(comp_path)
            or _discover_python_top_package(comp_path)
            or _discover_go_module_path(comp_path)
        )
        if pkg:
            comp.boundaries.append(
                ComponentBoundary(
                    boundary_type="package",
                    path=pkg,
                    repo=primary.repo,
                )
            )


def _deduplicate_components(components: list[Component]) -> list[Component]:
    """Remove components that overlap by boundary path, preferring more specific ones."""
    if not components:
        return []

    by_path: dict[str, list[Component]] = {}
    for comp in components:
        for boundary in comp.boundaries:
            key = f"{boundary.repo or ''}:{boundary.path}"
            by_path.setdefault(key, []).append(comp)

    seen_ids: set[str] = set()
    result: list[Component] = []

    sorted_comps = sorted(
        components,
        key=lambda c: (
            0 if c.boundaries and c.boundaries[0].boundary_type == "module" else 1,
            c.name,
        ),
    )

    for comp in sorted_comps:
        if comp.id not in seen_ids:
            seen_ids.add(comp.id)
            result.append(comp)

    return result


def discover_components(
    repo_path: Path,
    repo_name: str | None = None,
    include_root: bool = True,
) -> list[Component]:
    """Discover architectural components in a repository.

    Applies multiple discovery strategies in priority order:
    1. Monorepo directories (packages/, services/, apps/, etc.)
    2. Build-system modules (Maven multi-module, Gradle sub-projects)
    3. Nested build components (subdirs with own build files)
    4. ML pipeline directories (requirements.txt + Python scripts)
    5. C++ source subdirectories (source/ml/, source/transforms/, etc.)
    6. Kubernetes workloads
    7. Docker Compose services
    8. Root project (if nothing else found or include_root=True)

    Returns a deduplicated list of Component objects.
    """
    effective_name = repo_name or repo_path.name
    logger.info("Discovering components in %s", repo_path)

    all_components: list[Component] = []

    # Strategy 1: Monorepo structure
    mono_comps = _discover_monorepo_components(repo_path, effective_name)
    all_components.extend(mono_comps)
    if mono_comps:
        logger.info("Found %d monorepo components", len(mono_comps))

    # Strategy 2: Build-system modules
    maven_comps = _discover_multi_module_maven(repo_path, effective_name)
    all_components.extend(maven_comps)
    if maven_comps:
        logger.info("Found %d Maven modules", len(maven_comps))

    gradle_comps = _discover_gradle_subprojects(repo_path, effective_name)
    all_components.extend(gradle_comps)
    if gradle_comps:
        logger.info("Found %d Gradle sub-projects", len(gradle_comps))

    # Strategy 3: Nested build components (subdirs with own build files)
    nested_comps = _discover_nested_build_components(repo_path, effective_name)
    all_components.extend(nested_comps)
    if nested_comps:
        logger.info("Found %d nested build components", len(nested_comps))

    # Strategy 4: ML pipeline directories (requirements.txt + Python scripts)
    ml_comps = _discover_ml_pipeline_components(repo_path, effective_name)
    all_components.extend(ml_comps)
    if ml_comps:
        logger.info("Found %d ML pipeline components", len(ml_comps))

    # Strategy 5: C++ source subdirectories
    src_comps = _discover_source_subdirectories(repo_path, effective_name)
    all_components.extend(src_comps)
    if src_comps:
        logger.info("Found %d source sub-components", len(src_comps))

    # Strategy 6: Kubernetes workloads
    k8s_comps = _discover_k8s_components(repo_path, effective_name)
    all_components.extend(k8s_comps)
    if k8s_comps:
        logger.info("Found %d K8s workloads", len(k8s_comps))

    # Strategy 7: Docker Compose services
    compose_comps = _discover_docker_compose_components(repo_path, effective_name)
    all_components.extend(compose_comps)
    if compose_comps:
        logger.info("Found %d Docker Compose services", len(compose_comps))

    # Strategy 8: Root component (skip when nested build components supersede it)
    if not nested_comps and (include_root or not all_components):
        root_comp = _discover_build_root_component(repo_path, effective_name)
        if root_comp is not None:
            all_components.append(root_comp)

    result = _deduplicate_components(all_components)
    _enrich_package_boundaries(result, repo_path)
    logger.info("Total components discovered: %d", len(result))
    return result


def discover_components_multi_repo(
    repo_paths: list[Path],
    repo_names: list[str] | None = None,
) -> list[Component]:
    """Discover components across multiple repositories.

    Returns a unified list with repo attribution on each component.
    """
    if repo_names and len(repo_names) != len(repo_paths):
        raise ValueError("repo_names must match repo_paths in length")

    all_components: list[Component] = []
    for i, repo_path in enumerate(repo_paths):
        name = repo_names[i] if repo_names else None
        comps = discover_components(repo_path, repo_name=name)
        all_components.extend(comps)

    return all_components


@dataclass
class DvcStage:
    """A single stage parsed from a DVC pipeline definition."""

    name: str
    cmd: str
    deps: list[str] = field(default_factory=list)
    outs: list[str] = field(default_factory=list)
    params: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)


@dataclass
class DvcPipeline:
    """Parsed DVC pipeline with stages and computed DAG edges."""

    stages: list[DvcStage] = field(default_factory=list)
    edges: list[tuple[str, str]] = field(default_factory=list)


def _extract_dvc_paths(value: Any) -> list[str]:
    """Extract file paths from a DVC deps/outs/params/metrics entry.

    DVC supports both simple string lists and dicts with path keys.
    """
    if value is None:
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict):
            path = item.get("path") or item.get("fname")
            if path:
                result.append(str(path))
            elif len(item) == 1:
                result.append(str(next(iter(item.values()))))
    return result


def parse_dvc_pipeline(dvc_yaml_path: Path) -> DvcPipeline | None:
    """Parse a dvc.yaml file into a DvcPipeline with stages and DAG edges.

    Returns None if the file cannot be parsed or contains no stages.
    """
    yaml = YAML(typ="safe")
    try:
        data = yaml.load(dvc_yaml_path)
    except (YAMLError, OSError):
        logger.debug("Failed to parse DVC pipeline: %s", dvc_yaml_path, exc_info=True)
        return None

    if not isinstance(data, dict):
        return None

    stages_data = data.get("stages")
    if not isinstance(stages_data, dict) or not stages_data:
        return None

    stages: list[DvcStage] = []
    for stage_name, stage_def in stages_data.items():
        if not isinstance(stage_def, dict):
            continue
        cmd = stage_def.get("cmd", "")
        if isinstance(cmd, list):
            cmd = " && ".join(str(c) for c in cmd)
        stages.append(
            DvcStage(
                name=str(stage_name),
                cmd=str(cmd),
                deps=_extract_dvc_paths(stage_def.get("deps")),
                outs=_extract_dvc_paths(stage_def.get("outs")),
                params=_extract_dvc_paths(stage_def.get("params")),
                metrics=_extract_dvc_paths(stage_def.get("metrics")),
            )
        )

    if not stages:
        return None

    # Compute DAG edges: stage A -> stage B when any output of A is a dep of B
    outs_to_stage: dict[str, str] = {}
    for stage in stages:
        for out in stage.outs:
            outs_to_stage[out] = stage.name

    edges: list[tuple[str, str]] = []
    for stage in stages:
        for dep in stage.deps:
            producer = outs_to_stage.get(dep)
            if producer and producer != stage.name:
                edges.append((producer, stage.name))

    logger.debug(
        "Parsed DVC pipeline: %d stages, %d edges from %s",
        len(stages),
        len(edges),
        dvc_yaml_path,
    )

    return DvcPipeline(stages=stages, edges=edges)


__all__ = [
    "DvcPipeline",
    "DvcStage",
    "discover_components",
    "discover_components_multi_repo",
    "parse_dvc_pipeline",
]
