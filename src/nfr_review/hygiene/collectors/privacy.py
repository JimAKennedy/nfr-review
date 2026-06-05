# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Privacy collector — scans source files for PII patterns, internal
organization references, and hardcoded tracking/analytics IDs.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from nfr_review.collectors.payloads.privacy import PrivacyMatch, PrivacyPayload
from nfr_review.hygiene import hygiene_collector_registry
from nfr_review.models import Evidence
from nfr_review.path_filter import iter_repo_files

_FALSE_POSITIVE_FILES = frozenset(
    {
        "pyproject.toml",
        "package.json",
        "setup.cfg",
        "setup.py",
        "LICENSE",
        "LICENSE.md",
        "LICENSE.txt",
        ".gitconfig",
        ".gitmodules",
        ".mailmap",
    }
)

_BINARY_EXTENSIONS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".bmp",
        ".webp",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".otf",
        ".zip",
        ".tar",
        ".gz",
        ".bz2",
        ".xz",
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".pyc",
        ".pyo",
        ".class",
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".db",
        ".sqlite",
        ".sqlite3",
    }
)

_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(
    r"(?<!\d)"
    r"(?:\+?1[-.\s]?)?"
    r"(?:\(?\d{3}\)?[-.\s]?)"
    r"\d{3}[-.\s]?\d{4}"
    r"(?!\d)"
)
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CC_RE = re.compile(r"\b(?:\d{4}[-\s]){3}\d{4}\b")

_INTERNAL_DOMAIN_RE = re.compile(
    r"\b[a-zA-Z0-9-]+\."
    r"(?:internal|corp|local|intranet)"
    r"(?:\.[a-zA-Z]{2,})?\b"
)
_INTERNAL_IP_RE = re.compile(
    r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3})\b"
)

_GA_RE = re.compile(r"\b(?:UA-\d{4,10}-\d{1,4}|G-[A-Z0-9]{10,})\b")
_FB_PIXEL_RE = re.compile(r"(?:fbq\s*\(\s*['\"]init['\"]|\bFB_PIXEL_ID\b)")
_SEGMENT_RE = re.compile(r"\bwriteKey\s*[:=]\s*['\"][a-zA-Z0-9]{20,}['\"]")
_MIXPANEL_RE = re.compile(r"\bmixpanel\.init\s*\(\s*['\"][a-f0-9]{20,}['\"]")

_TEST_CARD_NUMBERS = frozenset(
    {
        "4242424242424242",
        "5555555555554444",
        "5105105105105100",
        "4000056000000002",
        "4111111111111111",
    }
)

_SNIPPET_MAX = 40


def _is_reserved_ssn(value: str) -> bool:
    digits = value.replace("-", "")
    area = int(digits[:3])
    if area == 0 or area == 666 or 900 <= area <= 999:
        return True
    if digits.startswith("98765432"):
        return True
    return False


def _is_test_card(value: str) -> bool:
    digits = value.replace("-", "").replace(" ", "")
    return digits in _TEST_CARD_NUMBERS


def _truncate(text: str) -> str:
    if len(text) <= _SNIPPET_MAX:
        return text
    return text[:_SNIPPET_MAX] + "..."


def _is_binary(path: Path) -> bool:
    return path.suffix.lower() in _BINARY_EXTENSIONS


def _is_false_positive_file(rel_path: str) -> bool:
    return Path(rel_path).name in _FALSE_POSITIVE_FILES


def _read_safe(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return None


def _scan_pii(rel_path: str, text: str, *, is_config: bool) -> list[PrivacyMatch]:
    matches: list[PrivacyMatch] = []

    for i, line in enumerate(text.splitlines(), 1):
        for _m in _SSN_RE.finditer(line):
            if not _is_reserved_ssn(_m.group()):
                matches.append(
                    PrivacyMatch(
                        file=rel_path,
                        line=i,
                        pattern_type="ssn",
                        snippet=_truncate(line.strip()),
                    )
                )
        for _m in _CC_RE.finditer(line):
            if not _is_test_card(_m.group()):
                matches.append(
                    PrivacyMatch(
                        file=rel_path,
                        line=i,
                        pattern_type="credit_card",
                        snippet=_truncate(line.strip()),
                    )
                )
        if not is_config:
            for _m in _EMAIL_RE.finditer(line):
                matches.append(
                    PrivacyMatch(
                        file=rel_path,
                        line=i,
                        pattern_type="email",
                        snippet=_truncate(line.strip()),
                    )
                )
            for _m in _PHONE_RE.finditer(line):
                matches.append(
                    PrivacyMatch(
                        file=rel_path,
                        line=i,
                        pattern_type="phone",
                        snippet=_truncate(line.strip()),
                    )
                )

    return matches


def _scan_internal_refs(rel_path: str, text: str) -> list[PrivacyMatch]:
    matches: list[PrivacyMatch] = []
    for i, line in enumerate(text.splitlines(), 1):
        for _m in _INTERNAL_DOMAIN_RE.finditer(line):
            matches.append(
                PrivacyMatch(
                    file=rel_path,
                    line=i,
                    pattern_type="internal_domain",
                    snippet=_truncate(line.strip()),
                )
            )
        for _m in _INTERNAL_IP_RE.finditer(line):
            matches.append(
                PrivacyMatch(
                    file=rel_path,
                    line=i,
                    pattern_type="internal_ip",
                    snippet=_truncate(line.strip()),
                )
            )
    return matches


def _scan_tracking_ids(rel_path: str, text: str) -> list[PrivacyMatch]:
    matches: list[PrivacyMatch] = []
    for i, line in enumerate(text.splitlines(), 1):
        if "environ" in line or "getenv" in line or "os.env" in line:
            continue
        for label, pat in (
            ("google_analytics", _GA_RE),
            ("facebook_pixel", _FB_PIXEL_RE),
            ("segment_write_key", _SEGMENT_RE),
            ("mixpanel_token", _MIXPANEL_RE),
        ):
            for _m in pat.finditer(line):
                matches.append(
                    PrivacyMatch(
                        file=rel_path,
                        line=i,
                        pattern_type=label,
                        snippet=_truncate(line.strip()),
                    )
                )
    return matches


class PrivacyCollector:
    name = "privacy"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        pii_matches: list[PrivacyMatch] = []
        internal_refs: list[PrivacyMatch] = []
        tracking_ids: list[PrivacyMatch] = []
        files_scanned = 0

        for path in iter_repo_files(repo_path):
            if _is_binary(path):
                continue

            rel = str(path.relative_to(repo_path))
            text = _read_safe(path)
            if text is None:
                continue

            files_scanned += 1
            is_config = _is_false_positive_file(rel)

            pii_matches.extend(_scan_pii(rel, text, is_config=is_config))
            if not is_config:
                internal_refs.extend(_scan_internal_refs(rel, text))
                tracking_ids.extend(_scan_tracking_ids(rel, text))

        return [
            Evidence(
                collector_name=self.name,
                collector_version=self.version,
                locator=".",
                kind="privacy-analysis",
                payload=PrivacyPayload(
                    pii_matches=pii_matches,
                    internal_references=internal_refs,
                    tracking_ids=tracking_ids,
                    files_scanned=files_scanned,
                ),
            )
        ]


def _register() -> None:
    if "privacy" not in hygiene_collector_registry:
        hygiene_collector_registry.register("privacy", PrivacyCollector())


_register()

__all__ = ["PrivacyCollector"]
