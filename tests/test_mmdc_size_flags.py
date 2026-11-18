# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""render_mermaid_to_png passes size flags the installed mmdc understands.

mermaid-cli 12 removed ``-w``/``-H`` (viewport width/height) in favour of
``--size`` (maximum PNG dimension). Passing ``-w`` to mmdc 12 fails with
``error: unknown option '-w'`` and the architecture diagram is dropped.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from nfr_review.output import render


@pytest.fixture(autouse=True)
def _clear_version_cache() -> None:
    render._mmdc_major_version.cache_clear()


def _render_cmd(tmp_path: Path, version_stdout: str, **kwargs: int) -> list[str]:
    """Run render_mermaid_to_png against a fake mmdc; return the render argv."""
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if cmd[1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=version_stdout, stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    with (
        patch("nfr_review.output.render.shutil.which", return_value="/usr/bin/mmdc"),
        patch("nfr_review.output.render.subprocess.run", side_effect=fake_run),
    ):
        render.render_mermaid_to_png("graph TD; A-->B", tmp_path / "out.png", **kwargs)

    render_calls = [c for c in calls if "-i" in c]
    assert len(render_calls) == 1
    return render_calls[0]


def test_mmdc_12_gets_size_not_width_height(tmp_path: Path) -> None:
    cmd = _render_cmd(tmp_path, "12.2.0\n", width=2400, height=1600)

    assert "-w" not in cmd
    assert "-H" not in cmd
    assert cmd[cmd.index("--size") + 1] == "2400"


def test_mmdc_12_size_uses_larger_dimension(tmp_path: Path) -> None:
    cmd = _render_cmd(tmp_path, "12.0.0\n", width=800, height=3000)

    assert cmd[cmd.index("--size") + 1] == "3000"


def test_mmdc_11_keeps_width_and_height(tmp_path: Path) -> None:
    cmd = _render_cmd(tmp_path, "11.15.0\n", width=2400, height=1600)

    assert cmd[cmd.index("-w") + 1] == "2400"
    assert cmd[cmd.index("-H") + 1] == "1600"
    assert "--size" not in cmd


def test_unknown_mmdc_version_omits_size_flags(tmp_path: Path) -> None:
    cmd = _render_cmd(tmp_path, "not a version\n", width=2400, height=1600)

    assert not {"-w", "-H", "--size"} & set(cmd)


def test_no_size_requested_probes_nothing(tmp_path: Path) -> None:
    cmd = _render_cmd(tmp_path, "12.2.0\n")

    assert not {"-w", "-H", "--size"} & set(cmd)
