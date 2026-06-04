# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for rule metadata completeness and structure."""

from __future__ import annotations

import nfr_review.rules  # noqa: F401 — triggers auto-registration
from nfr_review.registry import rule_registry
from nfr_review.rule_metadata import RULE_METADATA, RuleMetadata, get_metadata

VALID_CATEGORIES = {"security", "reliability", "performance", "maintainability"}
VALID_SEVERITIES = {"critical", "high", "medium", "low", "info"}


def test_every_registered_rule_has_metadata() -> None:
    """Every rule in the registry must have an entry in RULE_METADATA."""
    rules = rule_registry.all()
    assert len(rules) > 0, "No rules registered"

    missing = [r.id for r in rules if r.id not in RULE_METADATA]
    assert missing == [], f"Rules missing metadata: {missing}"


def test_metadata_required_fields_populated() -> None:
    """Every metadata entry must have all required fields non-empty."""
    for rule_id, meta in RULE_METADATA.items():
        assert isinstance(meta, RuleMetadata), f"{rule_id}: not a RuleMetadata instance"
        assert meta.severity in VALID_SEVERITIES, (
            f"{rule_id}: invalid severity {meta.severity}"
        )
        assert meta.category in VALID_CATEGORIES, (
            f"{rule_id}: invalid category {meta.category}"
        )
        assert meta.description, f"{rule_id}: empty description"
        assert len(meta.description) >= 20, f"{rule_id}: description too short"


def test_metadata_tags_are_lowercase() -> None:
    """Tags should be lowercase kebab-case for consistency."""
    for rule_id, meta in RULE_METADATA.items():
        for tag in meta.tags:
            assert tag == tag.lower(), f"{rule_id}: tag {tag!r} should be lowercase"
            assert " " not in tag, f"{rule_id}: tag {tag!r} should not contain spaces"


def test_metadata_compliance_refs_format() -> None:
    """Compliance refs should follow 'Standard:Section' format."""
    for rule_id, meta in RULE_METADATA.items():
        for ref in meta.compliance_refs:
            assert ":" in ref, f"{rule_id}: compliance ref {ref!r} should contain ':'"


def test_get_metadata_returns_entry() -> None:
    """get_metadata returns RuleMetadata for known rules, None for unknown."""
    meta = get_metadata("ci-security-scan-missing")
    assert meta is not None
    assert meta.severity == "high"
    assert meta.category == "security"

    assert get_metadata("nonexistent-rule-xyz") is None


def test_metadata_count_matches_registry() -> None:
    """RULE_METADATA should cover exactly the registered rules (no orphans)."""
    rules = rule_registry.all()
    registered_ids = {r.id for r in rules}
    metadata_ids = set(RULE_METADATA.keys())

    orphan_metadata = metadata_ids - registered_ids
    assert orphan_metadata == set(), f"Metadata for non-existent rules: {orphan_metadata}"
