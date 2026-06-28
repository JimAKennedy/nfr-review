"""Regression test fixtures and helpers.

Provides clone-on-demand repo management, JSONL snapshot normalization,
and the --update-snapshots CLI flag for baseline regeneration.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from filelock import FileLock
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


def _ensure_checkout(clone_dir: Path, commit_sha: str, url: str) -> None:
    """Verify *clone_dir* is at *commit_sha*, re-cloning if the SHA is unreachable."""
    name = clone_dir.name
    head = subprocess.run(
        ["git", "-C", str(clone_dir), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    current = head.stdout.strip() if head.returncode == 0 else "<unknown>"
    if current == commit_sha:
        print(f"[checkout] {name}: HEAD={current[:12]} matches pin", flush=True)
        _reset_working_tree(clone_dir, name)
        return

    print(
        f"[checkout] {name}: HEAD={current[:12]} != pin={commit_sha[:12]}, fixing",
        flush=True,
    )

    fetch = subprocess.run(
        ["git", "-C", str(clone_dir), "fetch", "origin", commit_sha],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if fetch.returncode == 0:
        checkout = subprocess.run(
            ["git", "-C", str(clone_dir), "checkout", commit_sha],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if checkout.returncode == 0:
            _verify_head(clone_dir, commit_sha, name)
            return

    print(f"[checkout] {name}: fetch/checkout failed, re-cloning blobless", flush=True)
    shutil.rmtree(clone_dir, ignore_errors=True)
    subprocess.run(
        [
            "git",
            "clone",
            "--filter=blob:none",
            url,
            str(clone_dir),
        ],
        capture_output=True,
        text=True,
        timeout=600,
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(clone_dir), "checkout", commit_sha],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    _verify_head(clone_dir, commit_sha, name)


def _verify_head(clone_dir: Path, expected_sha: str, name: str) -> None:
    """Hard-fail if HEAD doesn't match the expected SHA after checkout."""
    actual = subprocess.run(
        ["git", "-C", str(clone_dir), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    ).stdout.strip()
    if actual != expected_sha:
        raise RuntimeError(
            f"[checkout] {name}: HEAD={actual} after checkout, expected {expected_sha}"
        )
    _reset_working_tree(clone_dir, name)


def _reset_working_tree(clone_dir: Path, name: str) -> None:
    """Reset the working tree to HEAD, discarding any stale modifications.

    Always runs ``clean -fdx`` so gitignored build artifacts (e.g.
    Maven-generated PackageVersion.java) are removed even when the
    tree looks clean to ``git status --porcelain`` (which hides
    ignored files).
    """
    subprocess.run(
        ["git", "-C", str(clone_dir), "checkout", "--", "."],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    result = subprocess.run(
        ["git", "-C", str(clone_dir), "clean", "-fdx"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        cleaned = len(result.stdout.strip().splitlines())
        print(
            f"[checkout] {name}: cleaned {cleaned} untracked/ignored file(s)",
            flush=True,
        )


def clone_repo(
    name: str,
    url: str,
    commit_sha: str | None,
    repos_dir: Path,
) -> Path:
    clone_dir = repos_dir / name
    if clone_dir.exists():
        if commit_sha is not None:
            _ensure_checkout(clone_dir, commit_sha, url)
        return clone_dir

    lock = FileLock(repos_dir / f".{name}.lock", timeout=900)
    with lock:
        if clone_dir.exists():
            if commit_sha is not None:
                _ensure_checkout(clone_dir, commit_sha, url)
            return clone_dir

        try:
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--filter=blob:none",
                    url,
                    str(clone_dir),
                ],
                capture_output=True,
                text=True,
                timeout=600,
                check=True,
            )
        except subprocess.TimeoutExpired:
            pytest.skip(f"clone timed out after 600s: {url}")
        except subprocess.CalledProcessError as exc:
            pytest.skip(f"clone failed: {exc.stderr.strip()}")

        if commit_sha is not None:
            _ensure_checkout(clone_dir, commit_sha, url)

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


_STRUCTURE_STABLE_FIELDS = {
    "evidence_locator": "<structure>",
    "summary": "<structure>",
    "recommendation": "<structure>",
}


def _normalize_structure_finding(record: dict) -> dict:
    """Stabilize non-deterministic output from graphify's Leiden clustering.

    Leiden assigns arbitrary community IDs and produces different cluster
    compositions across runs, changing edge counts, percentages, and even
    finding counts.  Replace content fields with placeholders so snapshot
    comparison only verifies: (1) the rule fires, (2) the RAG/severity is
    stable, and (3) the pattern_tag is correct.
    """
    record = dict(record)
    for field, placeholder in _STRUCTURE_STABLE_FIELDS.items():
        record[field] = placeholder
    return record


_DSL_VERSION_RE = re.compile(r"(Auto-generated by nfr-review v)\S+")


def normalize_dsl(dsl_text: str) -> str:
    """Stabilize non-deterministic content in Structurizr DSL output.

    Replaces the tool version string and sorts relationship lines
    (containing '->') within contiguous groups so that non-deterministic
    emission order does not cause snapshot mismatches.
    """
    text = _DSL_VERSION_RE.sub(r"\1<version>", dsl_text)
    lines = text.splitlines(keepends=True)
    result: list[str] = []
    rel_group: list[str] = []
    for line in lines:
        if "->" in line:
            rel_group.append(line)
        else:
            if rel_group:
                result.extend(sorted(rel_group))
                rel_group = []
            result.append(line)
    if rel_group:
        result.extend(sorted(rel_group))
    return "".join(result)


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
        # adr-gap findings from LLM-derived decisions are non-deterministic;
        # the LLM produces different specific decisions on each run.
        if record.get("rule_id") == "adr-gap" and record.get(
            "evidence_locator", ""
        ).startswith("adr-derived:"):
            continue
        record.pop("record_type", None)
        loc = record.get("evidence_locator", "")
        if loc.startswith("/"):
            record["evidence_locator"] = "."
        if record.get("rule_id") == "dep-freshness":
            record = _normalize_dep_freshness(record)
        if record.get("rule_id") == "dep-upgrade-path":
            record = _normalize_dep_upgrade_path(record)
        if record.get("rule_id", "").startswith("structure-"):
            record = _normalize_structure_finding(record)
        findings.append(record)
    findings.sort(
        key=lambda r: (
            r.get("rule_id", ""),
            r.get("evidence_locator", ""),
            r.get("summary", ""),
        )
    )
    return findings


_METADATA_FILE = "snapshot-metadata.json"


def _get_git_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        cwd=str(_PROJECT_ROOT),
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def write_snapshot_metadata(snapshot_dir: Path) -> None:
    """Write metadata about when and where snapshots were generated."""
    meta = {
        "generated_at": datetime.now(UTC).isoformat(),
        "nfr_review_sha": _get_git_sha(),
        "platform": platform.system(),
        "python_version": platform.python_version(),
        "ci": bool(os.environ.get("CI")),
    }
    meta_file = snapshot_dir / _METADATA_FILE
    meta_file.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def load_snapshot_metadata(snapshot_dir: Path) -> dict | None:
    """Load snapshot metadata if it exists."""
    meta_file = snapshot_dir / _METADATA_FILE
    if meta_file.exists():
        return json.loads(meta_file.read_text(encoding="utf-8"))
    return None
