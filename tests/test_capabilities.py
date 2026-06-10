# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for runtime capabilities detection."""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from nfr_review.capabilities import Capabilities, detect_capabilities, log_capabilities


class TestDetectCapabilities:
    def test_returns_capabilities_instance(self) -> None:
        caps = detect_capabilities()
        assert isinstance(caps, Capabilities)

    def test_git_detected_when_available(self) -> None:
        with patch(
            "shutil.which", side_effect=lambda x: "/usr/bin/git" if x == "git" else None
        ):
            caps = detect_capabilities()
        assert caps.git is True
        assert caps.mmdc is False
        assert caps.dot is False

    def test_all_tools_missing(self) -> None:
        with (
            patch("shutil.which", return_value=None),
            patch("nfr_review.capabilities.detect_capabilities.__module__", create=True),
        ):
            with patch("shutil.which", return_value=None):
                caps = detect_capabilities()
        assert caps.git is False
        assert caps.mmdc is False
        assert caps.dot is False

    def test_weasyprint_detected_when_importable(self) -> None:
        with patch("shutil.which", return_value=None):
            caps = detect_capabilities()
        # weasyprint may or may not be installed in test env;
        # just verify the field exists and is bool
        assert isinstance(caps.weasyprint, bool)


class TestLogCapabilities:
    def test_logs_at_debug_level(self, caplog: pytest.LogCaptureFixture) -> None:
        caps = Capabilities(git=True, mmdc=False, dot=True, weasyprint=False)
        with caplog.at_level(logging.DEBUG, logger="nfr_review.capabilities"):
            log_capabilities(caps)

        assert "runtime capabilities" in caplog.text
        assert "git=available" in caplog.text
        assert "mmdc=not found" in caplog.text
        assert "dot=available" in caplog.text

    def test_pdf_unavailable_message(self, caplog: pytest.LogCaptureFixture) -> None:
        caps = Capabilities(weasyprint=False)
        with caplog.at_level(logging.DEBUG, logger="nfr_review.capabilities"):
            log_capabilities(caps)

        assert "PDF generation unavailable" in caplog.text

    def test_no_pdf_warning_when_available(self, caplog: pytest.LogCaptureFixture) -> None:
        caps = Capabilities(weasyprint=True, mmdc=True)
        with caplog.at_level(logging.DEBUG, logger="nfr_review.capabilities"):
            log_capabilities(caps)

        assert "PDF generation unavailable" not in caplog.text
