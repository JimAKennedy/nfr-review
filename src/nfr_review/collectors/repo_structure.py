"""Repository structure collector — emits a single Evidence record describing
the top-level layout of the target repo (files, directories, presence of
common project markers).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nfr_review.models import Evidence
from nfr_review.registry import collector_registry

_README_PREFIX = "readme"


class RepoStructureCollector:
    name = "repo-structure"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        top_files: list[str] = []
        top_dirs: list[str] = []
        readme_name: str | None = None

        for entry in sorted(repo_path.iterdir(), key=lambda p: p.name):
            if entry.is_file():
                top_files.append(entry.name)
                if readme_name is None and entry.name.lower().startswith(_README_PREFIX):
                    readme_name = entry.name
            elif entry.is_dir():
                top_dirs.append(entry.name)

        payload: dict[str, Any] = {
            "top_level_files": top_files,
            "top_level_dirs": top_dirs,
            "has_readme": readme_name is not None,
            "readme_name": readme_name,
            "has_git_dir": (repo_path / ".git").exists(),
            "has_pyproject": (repo_path / "pyproject.toml").is_file(),
        }

        return [
            Evidence(
                collector_name=self.name,
                collector_version=self.version,
                locator=".",
                kind="repo-structure-summary",
                payload=payload,
            )
        ]


def _register() -> None:
    if "repo-structure" not in collector_registry:
        collector_registry.register("repo-structure", RepoStructureCollector())


_register()


__all__ = ["RepoStructureCollector"]
