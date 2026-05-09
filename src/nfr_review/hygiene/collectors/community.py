"""Community health file collector — checks for README, CONTRIBUTING,
CODE_OF_CONDUCT, SECURITY, CHANGELOG, and CODEOWNERS.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nfr_review.hygiene import hygiene_collector_registry
from nfr_review.models import Evidence

_README_NAMES = ("README.md", "README", "README.rst")
_SECURITY_PATHS = ("SECURITY.md", "SECURITY.txt", ".github/SECURITY.md")
_CHANGELOG_NAMES = ("CHANGELOG.md", "CHANGES.md", "HISTORY.md")
_CODEOWNERS_PATHS = (".github/CODEOWNERS", "CODEOWNERS")


def _find_file(repo_path: Path, candidates: tuple[str, ...] | list[str]) -> dict[str, Any]:
    for name in candidates:
        p = repo_path / name
        if p.is_file():
            size = p.stat().st_size
            return {"exists": True, "path": str(name), "size": size}
    return {"exists": False, "path": None, "size": 0}


class CommunityCollector:
    name = "community"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        payload: dict[str, Any] = {
            "readme": _find_file(repo_path, _README_NAMES),
            "contributing": _find_file(repo_path, ("CONTRIBUTING.md",)),
            "code_of_conduct": _find_file(repo_path, ("CODE_OF_CONDUCT.md",)),
            "security": _find_file(repo_path, _SECURITY_PATHS),
            "changelog": _find_file(repo_path, _CHANGELOG_NAMES),
            "codeowners": _find_file(repo_path, _CODEOWNERS_PATHS),
        }

        return [
            Evidence(
                collector_name=self.name,
                collector_version=self.version,
                locator=".",
                kind="community-analysis",
                payload=payload,
            )
        ]


def _register() -> None:
    if "community" not in hygiene_collector_registry:
        hygiene_collector_registry.register("community", CommunityCollector())


_register()

__all__ = ["CommunityCollector"]
