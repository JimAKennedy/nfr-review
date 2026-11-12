"""G1: tree-sitter-dockerfile is a dependency only where a 0.2 wheel exists.

PyPI publishes tree-sitter-dockerfile 0.2.0 as two wheels (macOS arm64 and
manylinux x86_64) and no sdist. Everywhere else the only installable release
is the 0.0.0a1 "coming soon" placeholder, which has no grammar in it, so the
requirement must not resolve there at all.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from packaging.markers import default_environment
from packaging.requirements import Requirement

_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _dockerfile_requirement() -> Requirement:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    matches = [
        req
        for req in (Requirement(line) for line in data["project"]["dependencies"])
        if req.name == "tree-sitter-dockerfile"
    ]
    assert len(matches) == 1, matches
    return matches[0]


def test_requires_the_first_real_grammar_release() -> None:
    assert str(_dockerfile_requirement().specifier) == ">=0.2"


@pytest.mark.parametrize(
    ("sys_platform", "platform_machine", "installed"),
    [
        ("darwin", "arm64", True),
        ("linux", "x86_64", True),
        ("linux", "aarch64", False),
        ("darwin", "x86_64", False),
        ("win32", "AMD64", False),
    ],
)
def test_marker_matches_the_published_wheels(
    sys_platform: str, platform_machine: str, installed: bool
) -> None:
    marker = _dockerfile_requirement().marker
    assert marker is not None
    env: dict[str, str] = {
        **default_environment(),
        "sys_platform": sys_platform,
        "platform_machine": platform_machine,
    }
    assert marker.evaluate(env) is installed
