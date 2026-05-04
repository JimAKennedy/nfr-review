"""Auditability utilities — git provenance + run metadata (R021).

Every run records full provenance so downstream consumers can reproduce or
explain a finding. ``read_git_info`` never raises; any subprocess failure is
captured as a ``GitInfo`` with the relevant fields set to ``None`` and an
``error`` string populated for diagnostic purposes.
"""

from __future__ import annotations

import subprocess  # nosec B404 — git invocation with hardcoded commands only
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nfr_review import __version__ as _TOOL_VERSION
from nfr_review.models import RunMetadata

_GIT_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class GitInfo:
    """Result of probing a directory for git provenance.

    On any failure (no git binary, target not a repo, timeout) ``sha``,
    ``branch`` and ``dirty`` are ``None`` and ``error`` carries a short
    human-readable string suitable for logging into ``RunMetadata.git_error``.
    """

    sha: str | None = None
    branch: str | None = None
    dirty: bool | None = None
    error: str | None = None


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Invoke ``git`` with list args, never shell=True, with a 5s timeout."""
    return subprocess.run(  # nosec B603 B607
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT_SECONDS,
        check=False,
    )


def read_git_info(repo_path: Path) -> GitInfo:
    """Return git SHA, branch, and dirty state for ``repo_path``.

    Never raises. On any failure returns a ``GitInfo`` with ``error`` set.
    """
    try:
        sha_proc = _run_git(["rev-parse", "HEAD"], repo_path)
    except FileNotFoundError:
        return GitInfo(error="git not available")
    except subprocess.TimeoutExpired:
        return GitInfo(error="git timeout after 5s")
    except OSError as exc:  # pragma: no cover — defensive
        return GitInfo(error=f"git invocation failed: {exc}")

    if sha_proc.returncode != 0:
        return GitInfo(error="not a git repository")

    sha = sha_proc.stdout.strip() or None

    try:
        branch_proc = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_path)
    except subprocess.TimeoutExpired:
        return GitInfo(sha=sha, error="git timeout after 5s")
    except OSError as exc:  # pragma: no cover — defensive
        return GitInfo(sha=sha, error=f"git invocation failed: {exc}")

    branch: str | None
    if branch_proc.returncode == 0:
        branch = branch_proc.stdout.strip() or None
    else:
        branch = None

    try:
        status_proc = _run_git(["status", "--porcelain"], repo_path)
    except subprocess.TimeoutExpired:
        return GitInfo(sha=sha, branch=branch, error="git timeout after 5s")
    except OSError as exc:  # pragma: no cover — defensive
        return GitInfo(sha=sha, branch=branch, error=f"git invocation failed: {exc}")

    if status_proc.returncode != 0:
        return GitInfo(
            sha=sha,
            branch=branch,
            error="git status failed",
        )

    dirty = bool(status_proc.stdout.strip())
    return GitInfo(sha=sha, branch=branch, dirty=dirty, error=None)


def build_run_metadata(
    target: Path,
    collectors: list[Any],
    rules_run: list[str],
    rules_skipped: list[dict[str, Any]],
) -> RunMetadata:
    """Assemble a ``RunMetadata`` record for the current scan run (R021).

    Parameters
    ----------
    target:
        Repository under analysis. Used both as the git probe root and as the
        ``target_repo`` field of the metadata.
    collectors:
        Iterable of objects that satisfy the ``Collector`` protocol — each
        must expose ``name`` and ``version`` attributes.
    rules_run:
        Rule IDs that were evaluated during the run.
    rules_skipped:
        List of ``{"rule_id": ..., "reason": ...}`` style dictionaries
        describing rules the run elected not to evaluate.
    """
    git_info = read_git_info(target)
    timestamp = datetime.now(UTC).isoformat()
    collector_versions = {c.name: c.version for c in collectors}

    return RunMetadata(
        tool_version=_TOOL_VERSION,
        target_repo=str(target),
        git_sha=git_info.sha,
        git_branch=git_info.branch,
        git_dirty=git_info.dirty,
        git_error=git_info.error,
        timestamp=timestamp,
        collector_versions=collector_versions,
        rules_run=list(rules_run),
        rules_skipped=list(rules_skipped),
    )


__all__ = ["GitInfo", "build_run_metadata", "read_git_info"]
