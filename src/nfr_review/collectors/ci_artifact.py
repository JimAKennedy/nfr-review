"""CI Artifact collector — discovers CI/CD pipeline configuration files and emits
per-file Evidence with structured payload for downstream NFR rules.

Evidence payload contract (kind="ci-pipeline"):
    file_path: str — path relative to repo_path
    ci_system: str — "github-actions" | "gitlab-ci" | "azure-devops" | "jenkins" | "circleci"
    has_test_step: bool — detects mvn test, gradle test, npm test, pytest, go test, etc.
    has_security_scan: bool — detects snyk, trivy, codeql, sonarqube, etc.
    job_names: list[str]
    step_names: list[str]

Evidence payload contract (kind="ci-summary"):
    total_pipelines: int
    ci_systems: list[str] — unique CI systems found
    any_test_step: bool
    any_security_scan: bool
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from nfr_review.models import Evidence
from nfr_review.registry import collector_registry

logger = logging.getLogger("nfr_review.collectors.ci_artifact")

_HIDDEN_DIRS = frozenset({".git", ".svn", ".hg", ".idea", ".vscode", "node_modules"})

_TEST_PATTERNS = re.compile(
    r"(mvn\s+test|gradle\s+test|npm\s+test|pytest|go\s+test|cargo\s+test"
    r"|dotnet\s+test|rake\s+test|bundle\s+exec\s+rspec)",
    re.IGNORECASE,
)

_SECURITY_KEYWORDS = frozenset(
    {
        "snyk",
        "trivy",
        "codeql",
        "sonarqube",
        "dependency-check",
        "owasp",
        "sast",
        "dast",
        "semgrep",
        "bandit",
        "safety",
    }
)

_CI_FILES: list[tuple[str, str]] = [
    (".gitlab-ci.yml", "gitlab-ci"),
    ("azure-pipelines.yml", "azure-devops"),
    (".circleci/config.yml", "circleci"),
    ("Jenkinsfile", "jenkins"),
]


def _is_hidden(rel: Path) -> bool:
    return any(part.startswith(".") or part in _HIDDEN_DIRS for part in rel.parts)


def _has_test_step_in_text(text: str) -> bool:
    return bool(_TEST_PATTERNS.search(text))


def _has_security_in_text(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in _SECURITY_KEYWORDS)


def _parse_github_actions(yaml_data: dict[str, Any]) -> dict[str, Any]:
    """Parse a GitHub Actions workflow YAML structure."""
    jobs = yaml_data.get("jobs", {})
    if not isinstance(jobs, dict):
        jobs = {}

    job_names: list[str] = list(jobs.keys())
    step_names: list[str] = []
    has_test = False
    has_security = False

    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps", [])
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict):
                continue
            name = step.get("name", "")
            if name:
                step_names.append(name)
            uses = step.get("uses", "")
            run_cmd = step.get("run", "")
            combined = f"{name} {uses} {run_cmd}"
            if _has_test_step_in_text(combined):
                has_test = True
            if _has_security_in_text(combined):
                has_security = True

    return {
        "job_names": job_names,
        "step_names": step_names,
        "has_test_step": has_test,
        "has_security_scan": has_security,
    }


def _parse_gitlab_ci(yaml_data: dict[str, Any]) -> dict[str, Any]:
    """Parse a GitLab CI YAML structure."""
    job_names: list[str] = []
    step_names: list[str] = []
    has_test = False
    has_security = False

    reserved = frozenset(
        {
            "stages",
            "variables",
            "image",
            "before_script",
            "after_script",
            "cache",
            "services",
            "include",
            "default",
            "workflow",
        }
    )

    for key, value in yaml_data.items():
        if key.startswith(".") or key in reserved:
            continue
        if not isinstance(value, dict):
            continue
        job_names.append(key)
        script = value.get("script", [])
        if isinstance(script, list):
            for cmd in script:
                if isinstance(cmd, str):
                    step_names.append(cmd)
                    if _has_test_step_in_text(cmd):
                        has_test = True
                    if _has_security_in_text(cmd):
                        has_security = True

    return {
        "job_names": job_names,
        "step_names": step_names,
        "has_test_step": has_test,
        "has_security_scan": has_security,
    }


def _parse_azure_pipelines(yaml_data: dict[str, Any]) -> dict[str, Any]:
    """Parse Azure Pipelines YAML structure."""
    job_names: list[str] = []
    step_names: list[str] = []
    has_test = False
    has_security = False

    stages = yaml_data.get("stages", [])
    if isinstance(stages, list):
        for stage in stages:
            if isinstance(stage, dict):
                jobs = stage.get("jobs", [])
                if isinstance(jobs, list):
                    for job in jobs:
                        if isinstance(job, dict):
                            name = job.get("job", job.get("displayName", ""))
                            if name:
                                job_names.append(name)

    steps = yaml_data.get("steps", [])
    if isinstance(steps, list):
        for step in steps:
            if isinstance(step, dict):
                name = step.get("displayName", step.get("task", ""))
                if name:
                    step_names.append(name)
                script = step.get("script", "")
                combined = f"{name} {script}"
                if _has_test_step_in_text(combined):
                    has_test = True
                if _has_security_in_text(combined):
                    has_security = True

    return {
        "job_names": job_names,
        "step_names": step_names,
        "has_test_step": has_test,
        "has_security_scan": has_security,
    }


class CiArtifactCollector:
    """Collect evidence from CI/CD pipeline configuration files."""

    name = "ci-artifact"
    version = "0.1.0"

    def __init__(self) -> None:
        self._yaml = YAML(typ="safe")

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        evidence: list[Evidence] = []
        ci_files = self._discover_files(repo_path)

        for ci_file, ci_system in ci_files:
            rel = ci_file.relative_to(repo_path)
            try:
                payload = self._parse_ci_file(ci_file, ci_system, repo_path)
            except Exception as exc:
                logger.warning("Error parsing %s: %s", rel, exc)
                continue

            if payload is None:
                continue

            evidence.append(
                Evidence(
                    collector_name=self.name,
                    collector_version=self.version,
                    locator=str(rel),
                    kind="ci-pipeline",
                    payload=payload,
                )
            )

        # Emit summary
        if evidence:
            ci_systems = list({ev.payload["ci_system"] for ev in evidence})
            any_test = any(ev.payload["has_test_step"] for ev in evidence)
            any_security = any(ev.payload["has_security_scan"] for ev in evidence)
            evidence.append(
                Evidence(
                    collector_name=self.name,
                    collector_version=self.version,
                    locator="ci-summary",
                    kind="ci-summary",
                    payload={
                        "total_pipelines": len(evidence),
                        "ci_systems": ci_systems,
                        "any_test_step": any_test,
                        "any_security_scan": any_security,
                    },
                )
            )

        return evidence

    def _discover_files(self, repo_path: Path) -> list[tuple[Path, str]]:
        """Discover CI configuration files."""
        found: list[tuple[Path, str]] = []

        # GitHub Actions workflows
        gh_dir = repo_path / ".github" / "workflows"
        if gh_dir.is_dir():
            for f in sorted(gh_dir.iterdir()):
                if f.suffix in (".yml", ".yaml") and f.is_file():
                    found.append((f, "github-actions"))

        # Other CI files
        for rel_path, ci_system in _CI_FILES:
            candidate = repo_path / rel_path
            if candidate.is_file():
                found.append((candidate, ci_system))

        return found

    def _parse_ci_file(
        self, ci_file: Path, ci_system: str, repo_path: Path
    ) -> dict[str, Any] | None:
        """Parse a CI config file and return payload."""
        rel = ci_file.relative_to(repo_path)

        if ci_system == "jenkins":
            return {
                "file_path": str(rel),
                "ci_system": ci_system,
                "has_test_step": False,
                "has_security_scan": False,
                "job_names": [],
                "step_names": [],
            }

        yaml_data = self._yaml.load(ci_file)
        if not isinstance(yaml_data, dict):
            return None

        if ci_system == "github-actions":
            parsed = _parse_github_actions(yaml_data)
        elif ci_system == "gitlab-ci":
            parsed = _parse_gitlab_ci(yaml_data)
        elif ci_system == "azure-devops":
            parsed = _parse_azure_pipelines(yaml_data)
        elif ci_system == "circleci":
            parsed = _parse_gitlab_ci(yaml_data)  # similar structure
        else:
            return None

        parsed["file_path"] = str(rel)
        parsed["ci_system"] = ci_system
        return parsed


def _register() -> None:
    if "ci-artifact" not in collector_registry:
        collector_registry.register("ci-artifact", CiArtifactCollector())


_register()

__all__ = ["CiArtifactCollector"]
