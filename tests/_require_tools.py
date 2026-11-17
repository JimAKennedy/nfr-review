# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Fail, rather than skip, tests whose external tool is missing — when asked to.

Tests that need an external tool skip with a reason ending in
"not installed" (``mmdc not installed``, ``opentelemetry-sdk not installed``).
That is right on a developer machine, but in CI a skip is reported as green,
so a job that lost a tool would stop testing without anyone noticing. With
``NFR_REQUIRE_TOOLS=1`` such skips become failures. Other skips (platform,
opt-in markers) are left alone.

The hooks are re-exported from ``tests/conftest.py``.
"""

from __future__ import annotations

import os

import pytest

ENV_VAR = "NFR_REQUIRE_TOOLS"
_MISSING_TOOL_MARKER = "not installed"


def _skip_reason(report: pytest.TestReport | pytest.CollectReport) -> str | None:
    if report.skipped and isinstance(report.longrepr, tuple) and len(report.longrepr) == 3:
        return str(report.longrepr[2])
    return None


def escalate_missing_tool_skip(report: pytest.TestReport | pytest.CollectReport) -> None:
    """Turn a "<tool> not installed" skip into a failure if ENV_VAR is "1"."""
    if os.environ.get(ENV_VAR) != "1":
        return
    reason = _skip_reason(report)
    if reason is None or _MISSING_TOOL_MARKER not in reason:
        return
    report.outcome = "failed"
    report.longrepr = f"{ENV_VAR}=1 requires every external tool, but: {reason}"


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]):  # noqa: ARG001
    report = yield
    escalate_missing_tool_skip(report)
    return report


@pytest.hookimpl(wrapper=True)
def pytest_make_collect_report(collector: pytest.Collector):  # noqa: ARG001
    report = yield
    escalate_missing_tool_skip(report)
    return report
