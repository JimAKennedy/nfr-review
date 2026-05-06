"""Regression test fixtures and helpers.

Provides clone-on-demand repo management, JSONL snapshot normalization,
and the --update-snapshots CLI flag for baseline regeneration.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from ruamel.yaml import YAML

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_yaml = YAML(typ="safe")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-snapshots",
        action="store_true",
        default=False,
        help="Regenerate regression snapshot baselines instead of comparing.",
    )


@pytest.fixture(scope="session")
def update_snapshots(request: pytest.FixtureRequest) -> bool:
    return bool(request.config.getoption("--update-snapshots"))


@pytest.fixture(scope="session")
def regression_repos_dir() -> Path:
    d = _PROJECT_ROOT / ".regression-repos"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture(scope="session")
def snapshot_dir() -> Path:
    return _PROJECT_ROOT / "tests" / "regression" / "snapshots"


def load_manifest() -> list[dict]:
    manifest_path = Path(__file__).resolve().parent / "manifest.yaml"
    data = _yaml.load(manifest_path)
    return data["repos"]


def clone_repo(
    name: str,
    url: str,
    commit_sha: str | None,
    repos_dir: Path,
) -> Path:
    clone_dir = repos_dir / name
    if clone_dir.exists():
        return clone_dir

    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", url, str(clone_dir)],
            capture_output=True,
            text=True,
            timeout=300,
            check=True,
        )
    except subprocess.TimeoutExpired:
        pytest.skip(f"clone timed out after 300s: {url}")
    except subprocess.CalledProcessError as exc:
        pytest.skip(f"clone failed: {exc.stderr.strip()}")

    if commit_sha is not None:
        subprocess.run(
            ["git", "-C", str(clone_dir), "fetch", "--depth", "1", "origin", commit_sha],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        subprocess.run(
            ["git", "-C", str(clone_dir), "checkout", commit_sha],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    return clone_dir


def normalize_findings(jsonl_path: Path) -> list[dict]:
    findings: list[dict] = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("record_type") != "finding":
            continue
        if record.get("rag") == "skipped":
            continue
        record.pop("record_type", None)
        findings.append(record)
    findings.sort(
        key=lambda r: (
            r.get("rule_id", ""),
            r.get("evidence_locator", ""),
            r.get("summary", ""),
        )
    )
    return findings
