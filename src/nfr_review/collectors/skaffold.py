"""Skaffold collector — parses skaffold.yaml and extracts build/deploy topology.

Evidence payload contract (kind="skaffold-analysis"):
    file_path: str — path relative to repo_path
    api_version: str — apiVersion field
    build: dict — build section (artifacts, tagPolicy, etc.)
    deploy: dict — deploy section
    profiles: list[dict] — profiles section (may be empty)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML, YAMLError

from nfr_review.models import Evidence
from nfr_review.registry import collector_registry

logger = logging.getLogger("nfr_review.collectors.skaffold")

_HIDDEN_DIRS = frozenset({".git", ".svn", ".hg", ".idea", ".vscode", "node_modules"})


class SkaffoldCollector:
    name = "skaffold"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        evidence: list[Evidence] = []
        yaml = YAML(typ="safe")

        for skaffold_file in sorted(repo_path.rglob("skaffold.yaml")):
            rel = skaffold_file.relative_to(repo_path)
            if any(part.startswith(".") or part in _HIDDEN_DIRS for part in rel.parts):
                continue

            try:
                content = skaffold_file.read_bytes()
            except OSError as exc:
                logger.debug("Cannot read %s: %s", rel, exc)
                continue

            try:
                doc = yaml.load(content)
            except YAMLError as exc:
                logger.debug("YAML parse error in %s: %s", rel, exc)
                continue

            if not isinstance(doc, dict):
                continue

            api_version = doc.get("apiVersion", "")
            if not isinstance(api_version, str) or "skaffold" not in api_version:
                continue

            build = doc.get("build", {}) or {}
            deploy = doc.get("deploy", {}) or {}
            profiles = doc.get("profiles", []) or []

            evidence.append(
                Evidence(
                    collector_name=self.name,
                    collector_version=self.version,
                    locator=str(rel),
                    kind="skaffold-analysis",
                    payload={
                        "file_path": str(rel),
                        "api_version": api_version,
                        "build": build,
                        "deploy": deploy,
                        "profiles": profiles,
                    },
                )
            )

        return evidence


def _register() -> None:
    if "skaffold" not in collector_registry:
        collector_registry.register("skaffold", SkaffoldCollector())


_register()

__all__ = ["SkaffoldCollector"]
