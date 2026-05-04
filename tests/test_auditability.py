from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from nfr_review import __version__ as TOOL_VERSION
from nfr_review.auditability import (
    GitInfo,
    build_run_metadata,
    read_git_info,
)


def _git(cwd: Path, *args: str) -> None:
    """Helper: run a git command in ``cwd`` for test fixture setup."""
    env = {
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "PATH": _system_path(),
    }
    subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        env=env,
    )


def _system_path() -> str:
    import os

    return os.environ.get("PATH", "/usr/bin:/bin")


def _has_git() -> bool:
    try:
        subprocess.run(
            ["git", "--version"],
            capture_output=True,
            check=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False
    return True


requires_git = pytest.mark.skipif(not _has_git(), reason="git binary not available")


def test_read_git_info_non_repo_returns_error(tmp_path: Path) -> None:
    info = read_git_info(tmp_path)
    assert isinstance(info, GitInfo)
    assert info.sha is None
    assert info.branch is None
    assert info.dirty is None
    assert info.error is not None
    assert "not a git repository" in info.error


@requires_git
def test_read_git_info_clean_repo(tmp_path: Path) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    (tmp_path / "README.md").write_text("hi\n")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-m", "initial")

    info = read_git_info(tmp_path)

    assert info.error is None
    assert info.sha is not None
    assert len(info.sha) == 40  # full SHA-1
    assert info.branch == "main"
    assert info.dirty is False


@requires_git
def test_read_git_info_dirty_repo(tmp_path: Path) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    (tmp_path / "README.md").write_text("hi\n")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-m", "initial")

    # Create an untracked file -> repo is dirty.
    (tmp_path / "scratch.txt").write_text("scratch\n")

    info = read_git_info(tmp_path)

    assert info.error is None
    assert info.sha is not None
    assert info.dirty is True


def test_read_git_info_handles_missing_git_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise_fnf(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("git not on PATH")

    monkeypatch.setattr(
        "nfr_review.auditability.subprocess.run", _raise_fnf
    )

    info = read_git_info(tmp_path)

    assert info.sha is None
    assert info.branch is None
    assert info.dirty is None
    assert info.error == "git not available"


def test_read_git_info_handles_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise_timeout(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd="git", timeout=5)

    monkeypatch.setattr(
        "nfr_review.auditability.subprocess.run", _raise_timeout
    )

    info = read_git_info(tmp_path)

    assert info.error == "git timeout after 5s"


def test_read_git_info_uses_list_args_and_no_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defence-in-depth: subprocess.run must be called with a list and no shell=True."""
    captured: list[dict] = []

    def _fake_run(args, **kwargs):  # type: ignore[no-untyped-def]
        captured.append({"args": args, "kwargs": kwargs})
        # Simulate "not a git repo" so we exit on the first call.
        return subprocess.CompletedProcess(
            args=args, returncode=128, stdout="", stderr="fatal: not a repo"
        )

    monkeypatch.setattr("nfr_review.auditability.subprocess.run", _fake_run)

    read_git_info(tmp_path)

    assert len(captured) == 1
    call = captured[0]
    assert isinstance(call["args"], list)
    assert call["args"][0] == "git"
    assert call["kwargs"].get("shell") in (None, False)
    assert call["kwargs"].get("timeout") == 5


def test_build_run_metadata_uses_utc_timestamp(tmp_path: Path) -> None:
    meta = build_run_metadata(
        target=tmp_path,
        collectors=[],
        rules_run=[],
        rules_skipped=[],
    )

    # Should parse as ISO-8601 with a UTC offset.
    parsed = datetime.fromisoformat(meta.timestamp)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() is not None
    assert parsed.utcoffset().total_seconds() == 0


def test_build_run_metadata_collector_versions(tmp_path: Path) -> None:
    collectors = [
        SimpleNamespace(name="repo_structure", version="0.1.0"),
        SimpleNamespace(name="dependency_audit", version="0.2.3"),
    ]

    meta = build_run_metadata(
        target=tmp_path,
        collectors=collectors,
        rules_run=["sample-readme-exists"],
        rules_skipped=[{"rule_id": "needs-llm", "reason": "no API key"}],
    )

    assert meta.tool_version == TOOL_VERSION
    assert meta.target_repo == str(tmp_path)
    assert meta.collector_versions == {
        "repo_structure": "0.1.0",
        "dependency_audit": "0.2.3",
    }
    assert meta.rules_run == ["sample-readme-exists"]
    assert meta.rules_skipped == [
        {"rule_id": "needs-llm", "reason": "no API key"}
    ]


def test_build_run_metadata_propagates_git_error_for_non_repo(
    tmp_path: Path,
) -> None:
    meta = build_run_metadata(
        target=tmp_path,
        collectors=[],
        rules_run=[],
        rules_skipped=[],
    )

    assert meta.git_sha is None
    assert meta.git_branch is None
    assert meta.git_dirty is None
    assert meta.git_error is not None


@requires_git
def test_build_run_metadata_populates_git_fields_for_real_repo(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    (tmp_path / "README.md").write_text("hi\n")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-m", "initial")

    meta = build_run_metadata(
        target=tmp_path,
        collectors=[SimpleNamespace(name="repo_structure", version="0.1.0")],
        rules_run=["r1"],
        rules_skipped=[],
    )

    assert meta.git_error is None
    assert meta.git_sha is not None and len(meta.git_sha) == 40
    assert meta.git_branch == "main"
    assert meta.git_dirty is False
    assert meta.collector_versions == {"repo_structure": "0.1.0"}
