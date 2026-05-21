# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""CI-automation collector — detects CI config files and extracts pipeline info."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML, YAMLError

from nfr_review.hygiene import hygiene_collector_registry
from nfr_review.models import Evidence

logger = logging.getLogger(__name__)

_CI_GLOBS: list[tuple[str, str]] = [
    (".github/workflows/*.yml", "github-actions"),
    (".github/workflows/*.yaml", "github-actions"),
    (".gitlab-ci.yml", "gitlab-ci"),
    ("Jenkinsfile", "jenkins"),
    (".circleci/config.yml", "circleci"),
    ("azure-pipelines.yml", "azure-devops"),
]


_yaml = YAML(typ="safe")


def _parse_github_actions(content: str) -> dict[str, Any]:
    try:
        doc = _yaml.load(content)
    except YAMLError:
        return {"parse_error": True, "jobs": [], "steps": []}

    if not isinstance(doc, dict):
        return {"parse_error": False, "jobs": [], "steps": []}

    jobs_section = doc.get("jobs", {})
    if not isinstance(jobs_section, dict):
        return {"parse_error": False, "jobs": [], "steps": []}

    job_names: list[str] = list(jobs_section.keys())
    steps: list[str] = []

    for job in jobs_section.values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps", []):
            if not isinstance(step, dict):
                continue
            if "run" in step:
                steps.append(str(step["run"]))
            if "uses" in step:
                steps.append(str(step["uses"]))

    return {"parse_error": False, "jobs": job_names, "steps": steps}


class CiAutomationCollector:
    name = "ci-automation"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        ci_systems: list[str] = []
        configs: list[dict[str, Any]] = []

        for pattern, provider in _CI_GLOBS:
            if "*" in pattern:
                parent = repo_path / Path(pattern).parent
                if not parent.is_dir():
                    continue
                suffix = Path(pattern).name
                glob_pat = suffix
                matches = list(parent.glob(glob_pat))
            else:
                candidate = repo_path / pattern
                matches = [candidate] if candidate.exists() else []

            for match_path in matches:
                if not match_path.is_file():
                    continue

                if provider not in ci_systems:
                    ci_systems.append(provider)

                rel_path = str(match_path.relative_to(repo_path))
                try:
                    raw = match_path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    logger.debug("Could not read CI config: %s", rel_path)
                    continue

                entry: dict[str, Any] = {
                    "path": rel_path,
                    "provider": provider,
                    "raw_content_length": len(raw),
                }

                if provider == "github-actions":
                    parsed = _parse_github_actions(raw)
                    entry["jobs"] = parsed["jobs"]
                    entry["steps"] = parsed["steps"]
                    if parsed.get("parse_error"):
                        logger.debug("Malformed YAML in %s — skipping parse", rel_path)
                else:
                    entry["jobs"] = []
                    entry["steps"] = []
                    entry["has_content"] = len(raw.strip()) > 0
                    # For non-GHA, try to extract step-like content from YAML
                    if provider in ("gitlab-ci", "circleci", "azure-devops"):
                        try:
                            doc = _yaml.load(raw)
                            if isinstance(doc, dict):
                                entry["raw_keys"] = list(doc.keys())
                                _extract_script_steps(doc, entry)
                        except YAMLError:
                            logger.debug("Malformed YAML in %s — skipping parse", rel_path)

                configs.append(entry)

        payload = {
            "ci_systems": ci_systems,
            "configs": configs,
            "has_ci": len(ci_systems) > 0,
        }

        return [
            Evidence(
                collector_name=self.name,
                collector_version=self.version,
                locator=".",
                kind="ci-automation-analysis",
                payload=payload,
            )
        ]


def _extract_script_steps(doc: dict[str, Any], entry: dict[str, Any]) -> None:
    """Best-effort extraction of script/step strings from GitLab/CircleCI/Azure YAML."""
    steps: list[str] = []
    _walk_for_scripts(doc, steps)
    if steps:
        entry["steps"] = steps


def _walk_for_scripts(node: Any, steps: list[str], depth: int = 0) -> None:
    if depth > 10:
        return
    if isinstance(node, dict):
        for key, val in node.items():
            if key in ("script", "run", "command") and isinstance(val, str):
                steps.append(val)
            elif key in ("script", "run", "command") and isinstance(val, list):
                for item in val:
                    if isinstance(item, str):
                        steps.append(item)
            else:
                _walk_for_scripts(val, steps, depth + 1)
    elif isinstance(node, list):
        for item in node:
            _walk_for_scripts(item, steps, depth + 1)


def _register() -> None:
    if "ci-automation" not in hygiene_collector_registry:
        hygiene_collector_registry.register("ci-automation", CiAutomationCollector())


_register()

__all__ = ["CiAutomationCollector"]
