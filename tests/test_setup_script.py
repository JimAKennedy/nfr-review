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
SETUP_ALL_SCRIPT = PROJECT_ROOT / "scripts" / "setup-all.sh"


@pytest.fixture()
def script_text() -> str:
    return SETUP_SCRIPT.read_text()


@pytest.fixture()
def all_script_text() -> str:
    return SETUP_ALL_SCRIPT.read_text()


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

    def test_has_llm_backend_menu(self, script_text: str) -> None:
        assert "NFR_LLM_BACKEND" in script_text
        assert "ANTHROPIC_API_KEY" in script_text
        assert "claude-cli" in script_text
        assert "read -rp" in script_text or "read -r" in script_text

    def test_has_stale_install_check(self, script_text: str) -> None:
        assert ".gsd/worktrees/" in script_text

    def test_skips_prompt_when_not_tty(self, script_text: str) -> None:
        assert "-t 0" in script_text


class TestSetupAllScriptStructure:
    def test_valid_bash_syntax(self) -> None:
        result = subprocess.run(
            ["bash", "-n", str(SETUP_ALL_SCRIPT)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"bash -n failed:\n{result.stderr}"

    def test_is_executable(self) -> None:
        mode = SETUP_ALL_SCRIPT.stat().st_mode
        assert mode & stat.S_IXUSR, "setup-all.sh is missing owner-execute bit"

    def test_has_safety_flags(self, all_script_text: str) -> None:
        assert "set -euo pipefail" in all_script_text

    def test_installs_all_extras(self, all_script_text: str) -> None:
        assert "[dev,scancode,diagrams,pdf]" in all_script_text

    def test_installs_helm(self, all_script_text: str) -> None:
        assert "helm" in all_script_text
        assert "brew install helm" in all_script_text

    def test_installs_graphviz_binary(self, all_script_text: str) -> None:
        assert "brew install graphviz" in all_script_text

    def test_verifies_scancode(self, all_script_text: str) -> None:
        assert "scancode" in all_script_text

    def test_has_llm_backend_menu(self, all_script_text: str) -> None:
        assert "NFR_LLM_BACKEND" in all_script_text
        assert "ANTHROPIC_API_KEY" in all_script_text
        assert "claude-cli" in all_script_text

    def test_has_stale_install_check(self, all_script_text: str) -> None:
        assert ".gsd/worktrees/" in all_script_text

    def test_skips_prompt_when_not_tty(self, all_script_text: str) -> None:
        assert "-t 0" in all_script_text

    def test_installs_java(self, all_script_text: str) -> None:
        assert "brew install openjdk@21" in all_script_text

    def test_finds_java_via_brew_prefix(self, all_script_text: str) -> None:
        assert "brew --prefix openjdk@21" in all_script_text
        assert "find_java_bin" in all_script_text

    def test_regenerates_broken_jdepend_wrapper(self, all_script_text: str) -> None:
        assert "JDEPEND_NEEDS_WRAPPER" in all_script_text
        assert "write_jdepend_wrapper" in all_script_text

    def test_installs_jdepend(self, all_script_text: str) -> None:
        assert "jdepend" in all_script_text
        assert "JDEPEND_VERSION" in all_script_text
