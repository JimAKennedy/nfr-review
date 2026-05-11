"""Structural tests for scripts/setup.sh.

These validate syntax, permissions, and key content patterns without
running a full install cycle (no venv creation or pip install).
"""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SETUP_SCRIPT = PROJECT_ROOT / "scripts" / "setup.sh"


@pytest.fixture()
def script_text() -> str:
    return SETUP_SCRIPT.read_text()


class TestSetupScriptStructure:
    def test_valid_bash_syntax(self) -> None:
        result = subprocess.run(
            ["bash", "-n", str(SETUP_SCRIPT)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"bash -n failed:\n{result.stderr}"

    def test_is_executable(self) -> None:
        mode = SETUP_SCRIPT.stat().st_mode
        assert mode & stat.S_IXUSR, "setup.sh is missing owner-execute bit"

    def test_has_safety_flags(self, script_text: str) -> None:
        assert "set -euo pipefail" in script_text

    def test_detects_python_version(self, script_text: str) -> None:
        assert "3, 11" in script_text or "3.11" in script_text
        assert "python3.11" in script_text

    def test_has_api_key_prompt(self, script_text: str) -> None:
        assert "ANTHROPIC_API_KEY" in script_text
        assert "read -rp" in script_text or "read -r" in script_text

    def test_has_stale_install_check(self, script_text: str) -> None:
        assert ".gsd/worktrees/" in script_text

    def test_skips_prompt_when_not_tty(self, script_text: str) -> None:
        assert "-t 0" in script_text
