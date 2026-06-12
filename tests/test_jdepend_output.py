# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for nfr_review.output.jdepend_section."""

from __future__ import annotations

from nfr_review.collectors.payloads.adr import AdrDocumentPayload, AdrSummaryPayload
from nfr_review.models import Evidence
from nfr_review.output.jdepend_section import (
    build_adr_section,
    build_derived_adrs_section,
    build_jdepend_section,
)


def _ev(kind: str, payload: dict | object, locator: str = "test") -> Evidence:
    return Evidence(
        collector_name="test-collector",
        collector_version="1.0.0",
        locator=locator,
        kind=kind,
        payload=payload,
    )


# ── build_jdepend_section ────────────────────────────────────────────


def test_jdepend_section_no_evidence():
    assert build_jdepend_section([]) == ""


def test_jdepend_section_no_matching_kind():
    ev = _ev("other-kind", {"foo": "bar"})
    assert build_jdepend_section([ev]) == ""


def test_jdepend_section_basic():
    packages = [
        {"name": "com.example.core", "ca": 5, "ce": 3, "a": 0.2, "i": 0.6, "d": 0.2},
    ]
    ev = _ev("jdepend-packages", {"packages": packages, "bytecode_dir": "target/classes"})
    result = build_jdepend_section([ev])
    assert "JDepend Structural Analysis" in result
    assert "com.example.core" in result


def test_jdepend_section_with_cycles():
    packages = [
        {"name": "com.a", "ca": 1, "ce": 1, "a": 0.0, "i": 0.5, "d": 0.5},
    ]
    ev = _ev(
        "jdepend-packages",
        {
            "packages": packages,
            "cycle_groups": [["com.a", "com.b", "com.a"]],
        },
    )
    result = build_jdepend_section([ev])
    assert "Package Cycles" in result
    assert "com.a → com.b → com.a" in result


def test_jdepend_section_multiple_modules():
    pkg1 = [{"name": "mod1.core", "ca": 0, "ce": 0, "a": 0.0, "i": 0.0, "d": 1.0}]
    pkg2 = [{"name": "mod2.api", "ca": 0, "ce": 0, "a": 0.0, "i": 0.0, "d": 0.0}]
    ev1 = _ev("jdepend-packages", {"packages": pkg1, "bytecode_dir": "module1"})
    ev2 = _ev("jdepend-packages", {"packages": pkg2, "bytecode_dir": "module2"})
    result = build_jdepend_section([ev1, ev2])
    assert "Module: `module1`" in result
    assert "Module: `module2`" in result


# ── build_derived_adrs_section ───────────────────────────────────────


def test_derived_adrs_no_evidence():
    assert build_derived_adrs_section([]) == ""


def test_derived_adrs_no_matching_kind():
    ev = _ev("other-kind", {})
    assert build_derived_adrs_section([ev]) == ""


def test_derived_adrs_basic():
    ev = _ev(
        "adr-derived",
        {
            "title": "Use PostgreSQL",
            "category": "infrastructure",
            "confidence": 0.85,
            "rationale": "Found connection strings and migration files.",
            "evidence_refs": ["src/db.py", "migrations/001.sql"],
        },
    )
    result = build_derived_adrs_section([ev])
    assert "Derived Architecture Decision Records" in result
    assert "Use PostgreSQL" in result
    assert "infrastructure" in result
    assert "85%" in result
    assert "src/db.py" in result


def test_derived_adrs_missing_optional_fields():
    ev = _ev("adr-derived", {"title": "Unknown", "category": "unknown", "confidence": 0.0})
    result = build_derived_adrs_section([ev])
    assert "Unknown" in result


# ── build_adr_section ────────────────────────────────────────────────


def test_adr_section_no_docs():
    assert build_adr_section([]) == ""


def test_adr_section_no_matching_kind():
    ev = _ev("other", {})
    assert build_adr_section([ev]) == ""


def test_adr_section_with_typed_payloads():
    doc = _ev(
        "adr-document",
        AdrDocumentPayload(
            file_path="docs/adr/0001.md",
            title="Use Spring Boot",
            status="accepted",
            superseded_by=None,
        ),
    )
    summary = _ev(
        "adr-summary",
        AdrSummaryPayload(
            total_adrs=3,
            statuses={"accepted": 2, "superseded": 1},
            has_lifecycle_tracking=True,
        ),
    )
    result = build_adr_section([doc, summary])
    assert "Architecture Decision Records" in result
    assert "3 ADRs" in result
    assert "Use Spring Boot" in result
    assert "accepted" in result
    assert "2 accepted" in result


def test_adr_section_with_dict_payloads():
    doc = _ev(
        "adr-document",
        {
            "file_path": "docs/adr/0001.md",
            "title": "Use React",
            "status": "proposed",
            "superseded_by": "0003",
        },
    )
    result = build_adr_section([doc])
    assert "Use React" in result
    assert "proposed" in result
    assert "0003" in result


def test_adr_section_dict_summary():
    doc = _ev("adr-document", {"file_path": "adr.md", "title": "Test"})
    summary = _ev(
        "adr-summary",
        {
            "total_adrs": 1,
            "statuses": {"accepted": 1},
            "has_lifecycle_tracking": True,
        },
    )
    result = build_adr_section([doc, summary])
    assert "1 ADRs" in result
    assert "1 accepted" in result


def test_adr_section_no_lifecycle():
    doc = _ev("adr-document", {"file_path": "adr.md"})
    summary = _ev(
        "adr-summary",
        {
            "total_adrs": 1,
            "statuses": {},
            "has_lifecycle_tracking": False,
        },
    )
    result = build_adr_section([doc, summary])
    assert "1 ADRs" in result
    assert "Status breakdown" not in result
