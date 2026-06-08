# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Subprocess wrapper for running pytest and capturing structured results."""

from __future__ import annotations

import re
import subprocess  # nosec B404
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class PytestResult:
    """Structured result of a pytest invocation."""

    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    duration_seconds: float = 0.0
    warnings: list[str] = field(default_factory=list)
    raw_output: str = ""
    exit_code: int = 0

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.skipped + self.errors


_SUMMARY_RE = re.compile(
    r"(?P<counts>[\d\w\s,]+)\s+in\s+(?P<duration>[\d.]+)s",
)

_COUNT_RE = re.compile(r"(\d+)\s+(passed|failed|skipped|error|errors|warnings?)")


def _parse_summary(output: str) -> PytestResult:
    """Parse pytest summary line into a PytestResult (without raw_output/exit_code)."""
    passed = 0
    failed = 0
    skipped = 0
    errors = 0
    duration_seconds = 0.0
    warnings: list[str] = []

    lines = output.strip().splitlines()
    for line in reversed(lines):
        match = _SUMMARY_RE.search(line)
        if match:
            duration_seconds = float(match.group("duration"))
            for count_match in _COUNT_RE.finditer(line):
                count = int(count_match.group(1))
                label = count_match.group(2)
                if label == "passed":
                    passed = count
                elif label == "failed":
                    failed = count
                elif label == "skipped":
                    skipped = count
                elif label in ("error", "errors"):
                    errors = count
                elif label in ("warning", "warnings"):
                    warnings = [f"{count} warnings emitted"]
            break

    return PytestResult(
        passed=passed,
        failed=failed,
        skipped=skipped,
        errors=errors,
        duration_seconds=duration_seconds,
        warnings=warnings,
    )


_EXPENSIVE_MARKERS = frozenset({"regression", "slow"})


def _detect_expensive_markers(target: Path) -> list[str]:
    """Return marker names from pyproject.toml matching expensive categories."""
    pyproject = target / "pyproject.toml"
    if not pyproject.is_file():
        return []
    try:
        with open(pyproject, "rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError):
        return []
    markers: list[str] = (
        data.get("tool", {}).get("pytest", {}).get("ini_options", {}).get("markers", [])
    )
    found: list[str] = []
    for m in markers:
        name = m.split(":")[0].strip()
        if name in _EXPENSIVE_MARKERS:
            found.append(name)
    return found


def run_pytest(target: Path, *, timeout: int = 600) -> PytestResult:
    """Run pytest against target directory and return structured results.

    Uses ``--tb=no -q`` for predictable summary output.  Automatically
    deselects tests marked ``regression`` or ``slow`` when those markers
    are declared in the target's ``pyproject.toml`` so that the health-check
    stays within the timeout budget.
    """
    cmd = ["python", "-m", "pytest", "--tb=no", "-q"]

    expensive = _detect_expensive_markers(target)
    if expensive:
        expr = " and ".join(f"not {m}" for m in sorted(expensive))
        cmd.extend(["-m", expr])

    cmd.append(str(target))

    try:
        proc = subprocess.run(  # nosec B603
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(target),
        )
    except FileNotFoundError:
        return PytestResult(raw_output="pytest not found", exit_code=-1)
    except subprocess.TimeoutExpired:
        return PytestResult(raw_output=f"pytest timed out after {timeout}s", exit_code=-1)

    output = proc.stdout + proc.stderr
    parsed = _parse_summary(output)

    return PytestResult(
        passed=parsed.passed,
        failed=parsed.failed,
        skipped=parsed.skipped,
        errors=parsed.errors,
        duration_seconds=parsed.duration_seconds,
        warnings=parsed.warnings,
        raw_output=output,
        exit_code=proc.returncode,
    )
