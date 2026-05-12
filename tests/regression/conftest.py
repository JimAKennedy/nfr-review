"""Regression test fixtures and helpers.

Provides clone-on-demand repo management, JSONL snapshot normalization,
and the --update-snapshots CLI flag for baseline regeneration.
"""

from __future__ import annotations

import json
import re
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


_DEP_FRESHNESS_MONTHS_RE = re.compile(r"no release in \d+ months")
_DEP_FRESHNESS_LATEST_SUMMARY_RE = re.compile(r"but latest is \S+ \(")
_DEP_FRESHNESS_DRIFT_RE = re.compile(r"\((major|minor|patch) drift\)")
_DEP_FRESHNESS_LATEST_REC_RE = re.compile(r"to \S+ to pick up")

_DRIFT_STABLE_FIELDS = {
    "rag": "<rag>",
    "severity": "<severity>",
    "pattern_tag": "<tag>",
}

_DEP_UPGRADE_RECOMMENDED_RE = re.compile(r"Recommended set: [^\n]+")
_DEP_UPGRADE_STUCK_RE = re.compile(r"\(resolved=\S+, latest=\S+, gap=\d+ majors?\)")
_DEP_UPGRADE_BLOCKING_RE = re.compile(r"Blocking constraints: [^\n]+")


def _normalize_dep_freshness(record: dict) -> dict:
    """Stabilize time-varying fields in dep-freshness findings.

    Month counts, upstream latest versions, and drift classifications all
    change independently of our code, so we replace them with placeholders
    before snapshot comparison.
    """
    record = dict(record)
    s = record.get("summary", "")
    s = _DEP_FRESHNESS_MONTHS_RE.sub("no release in N months", s)
    s = _DEP_FRESHNESS_LATEST_SUMMARY_RE.sub("but latest is <latest> (", s)
    s = _DEP_FRESHNESS_DRIFT_RE.sub("(<drift> drift)", s)
    record["summary"] = s
    r = record.get("recommendation", "")
    r = _DEP_FRESHNESS_LATEST_REC_RE.sub("to <latest> to pick up", r)
    record["recommendation"] = r
    if record.get("pattern_tag", "").startswith("stale-dep-"):
        for field, placeholder in _DRIFT_STABLE_FIELDS.items():
            record[field] = placeholder
    return record


def _normalize_dep_upgrade_path(record: dict) -> dict:
    """Stabilize version-specific fields in dep-upgrade-path findings.

    The solver returns exact resolved versions that drift with every upstream
    release.  Replace them with placeholders so snapshots stay stable.
    """
    record = dict(record)
    s = record.get("summary", "")
    s = _DEP_UPGRADE_RECOMMENDED_RE.sub("Recommended set: <versions>", s)
    s = _DEP_UPGRADE_STUCK_RE.sub("(<resolved/latest/gap>)", s)
    record["summary"] = s
    s = record.get("summary", "")
    s = _DEP_UPGRADE_BLOCKING_RE.sub("Blocking constraints: <constraints>", s)
    record["summary"] = s
    return record


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
        loc = record.get("evidence_locator", "")
        if loc.startswith("/"):
            record["evidence_locator"] = "."
        if record.get("rule_id") == "dep-freshness":
            record = _normalize_dep_freshness(record)
        if record.get("rule_id") == "dep-upgrade-path":
            record = _normalize_dep_upgrade_path(record)
        findings.append(record)
    findings.sort(
        key=lambda r: (
            r.get("rule_id", ""),
            r.get("evidence_locator", ""),
            r.get("summary", ""),
        )
    )
    return findings
