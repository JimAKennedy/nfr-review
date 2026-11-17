# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""NFR_REQUIRE_TOOLS=1 turns "<tool> not installed" skips into failures.

Locally a missing mmdc or opentelemetry-sdk is a reason to skip. In the
nightly job it means the job silently stopped testing something, so the skip
must go red instead.
"""

from __future__ import annotations

import pytest

from tests._require_tools import ENV_VAR, escalate_missing_tool_skip


def _report(outcome: str, reason: str = "") -> pytest.TestReport:
    longrepr = ("tests/x.py", 1, f"Skipped: {reason}") if outcome == "skipped" else None
    return pytest.TestReport(
        nodeid="tests/x.py::test_x",
        location=("tests/x.py", 1, "test_x"),
        keywords={},
        outcome=outcome,
        longrepr=longrepr,
        when="setup",
    )


def test_missing_tool_skip_fails_when_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_VAR, "1")
    rep = _report("skipped", "mmdc not installed")

    escalate_missing_tool_skip(rep)

    assert rep.failed
    assert "mmdc not installed" in str(rep.longrepr)
    assert ENV_VAR in str(rep.longrepr)


def test_missing_tool_skip_stays_skipped_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)
    rep = _report("skipped", "mmdc not installed")

    escalate_missing_tool_skip(rep)

    assert rep.skipped


def test_other_skips_are_untouched_when_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_VAR, "1")
    rep = _report("skipped", "Windows-only behaviour")

    escalate_missing_tool_skip(rep)

    assert rep.skipped


def test_passing_reports_are_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_VAR, "1")
    rep = _report("passed")

    escalate_missing_tool_skip(rep)

    assert rep.passed
