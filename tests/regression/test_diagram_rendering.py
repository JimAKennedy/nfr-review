"""Regression tests for Mermaid diagram rendering.

Runs ``nfr-review arch`` against corpus repos and the nfr-review repo itself,
failing on any ``mmdc failed`` warnings in stderr.  These tests exist because
Mermaid's parser is fragile around C++ template syntax (``<>``, ``::``, ``{}``,
``*``, ``;``), and regressions are only visible at render time — unit tests
on the sanitizer alone have proven insufficient.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.regression.conftest import clone_repo, load_manifest

_MMDC = shutil.which("mmdc")
requires_mmdc = pytest.mark.skipif(_MMDC is None, reason="mmdc not installed")

_MANIFEST = load_manifest()
_CPP_REPOS = [e for e in _MANIFEST if "cpp" in e.get("expected_techs", [])]
_CPP_REPO_NAMES = [e["name"] for e in _CPP_REPOS]
_CPP_REPO_MAP = {e["name"]: e for e in _CPP_REPOS}

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_MMDC_FAILED_RE = re.compile(r"mmdc failed \(rc=\d+\)")


def _check_mmdc_warnings(stderr: str, label: str) -> None:
    """Fail if *stderr* contains any mmdc failure warnings."""
    failures = _MMDC_FAILED_RE.findall(stderr)
    if failures:
        lines = [
            ln.strip()
            for ln in stderr.splitlines()
            if "mmdc failed" in ln or "Parse error" in ln
        ]
        detail = "\n  ".join(lines[:10])
        pytest.fail(
            f"Mermaid rendering produced {len(failures)} failure(s) for {label}:\n  {detail}"
        )


# ── Corpus diagram rendering (C++ repos) ─────────────────────────────────


@requires_mmdc
@pytest.mark.regression
@pytest.mark.timeout(600)
@pytest.mark.parametrize("repo_name", _CPP_REPO_NAMES)
def test_corpus_diagram_rendering(
    repo_name: str,
    tmp_path: Path,
    regression_repos_dir: Path,
) -> None:
    """Run arch diagram generation on a C++ corpus repo; assert zero mmdc failures."""
    entry = _CPP_REPO_MAP[repo_name]
    clone_dir = clone_repo(
        name=entry["name"],
        url=entry["url"],
        commit_sha=entry.get("commit_sha"),
        repos_dir=regression_repos_dir,
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "nfr_review.cli",
            "arch",
            str(clone_dir),
            "--output-dir",
            str(tmp_path),
            "--no-llm",
            "--format",
            "pdf",
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )

    assert result.returncode == 0, (
        f"nfr-review arch exited {result.returncode} for {repo_name}:\n{result.stderr[-2000:]}"
    )

    _check_mmdc_warnings(result.stderr, repo_name)


# ── Self-scan architecture rendering ──────────────────────────────────────


@requires_mmdc
@pytest.mark.regression
@pytest.mark.timeout(600)
def test_self_scan_diagram_rendering(tmp_path: Path) -> None:
    """Run architecture review on the nfr-review repo itself and assert zero mmdc failures."""
    wp = pytest.importorskip("weasyprint", reason="weasyprint not installed")  # noqa: F841

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "nfr_review.cli",
            "arch",
            str(_PROJECT_ROOT),
            "--output-dir",
            str(tmp_path),
            "--no-llm",
            "--format",
            "pdf",
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )

    assert result.returncode == 0, (
        f"nfr-review arch self-scan exited {result.returncode}:\n{result.stderr[-2000:]}"
    )

    _check_mmdc_warnings(result.stderr, "nfr-review (self)")

    pdf_files = list(tmp_path.glob("*architecture-report.pdf"))
    assert pdf_files, f"No architecture PDF was generated in {tmp_path}"
