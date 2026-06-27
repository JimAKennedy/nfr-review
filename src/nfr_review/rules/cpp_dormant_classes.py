# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: CPP-DORMANT — detects C++ classes with zero relationships.

A class with no inheritance, no field-type references from other classes,
no parameter/return-type dependencies, no friend declarations, and no
nesting relationships is architecturally orphaned.  This may indicate
dormant or dead code that should be removed or integrated.

The rule operates on enriched cpp-ast evidence — it aggregates class data
across all files in the repo and builds a relationship graph identical to
the one used by ``render_class_diagram`` in ``arch_diagrams.py``.
"""

from __future__ import annotations

import re
from typing import Any

from nfr_review.arch_diagrams import _CPP_TYPE_NOISE
from nfr_review.collectors.payloads.cpp_ast import CppAstFilePayload
from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.rules.framework import FieldRule, Hit, make_finding
from nfr_review.rules.rule_helpers import make_green_finding

_TOKEN_RE = re.compile(r"\b([A-Za-z_]\w*)\b")
_SUPPRESSION_ANNOTATIONS = frozenset(
    {"ownership-transfer", "framework-managed", "suppress-dormant"}
)


def _type_refs(type_str: str, known: set[str]) -> set[str]:
    """Extract known class names referenced in a C++ type string."""
    if not type_str:
        return set()
    return {
        tok
        for tok in _TOKEN_RE.findall(type_str)
        if tok in known and tok not in _CPP_TYPE_NOISE
    }


class CppDormantClassesRule(FieldRule[CppAstFilePayload]):
    id = "cpp-dormant-classes"
    band = 2
    collector_name = "cpp-ast"
    evidence_kind = "cpp-ast-file"
    payload_type = CppAstFilePayload
    pattern_tag = "cpp-dormant-class"
    required_tech = ["cpp"]
    default_confidence = 0.7
    all_clear_summary = "All classes are connected — no dormant classes detected."

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        relevant = [e for e in evidence if e.kind == self.evidence_kind]
        if not relevant:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no cpp-ast evidence available",
            )

        all_classes: list[dict] = []
        class_file: dict[str, str] = {}
        for ev in relevant:
            payload = ev.payload
            for cls in payload.classes:
                name = cls.get("name", "")
                if name:
                    all_classes.append(cls)
                    class_file[name] = payload.file_path

        if len(all_classes) < 2:
            return RuleResult(rule_id=self.id, findings=[])

        known_names = {c["name"] for c in all_classes}
        connected: set[str] = set()

        for cls in all_classes:
            name = cls["name"]

            for base in cls.get("base_classes", []):
                base_name = base.get("name", "")
                if base_name in known_names:
                    connected.add(name)
                    connected.add(base_name)

            for field in cls.get("fields", []):
                for ref in _type_refs(field.get("type", ""), known_names):
                    if ref != name:
                        connected.add(name)
                        connected.add(ref)

            for method in cls.get("methods", []):
                for type_str in [method.get("return_type", "")] + [
                    p.get("type", "") for p in method.get("parameters", [])
                ]:
                    for ref in _type_refs(type_str, known_names):
                        if ref != name:
                            connected.add(name)
                            connected.add(ref)

            for friend_name in cls.get("friends", []):
                if friend_name in known_names and friend_name != name:
                    connected.add(name)
                    connected.add(friend_name)

            outer = cls.get("outer_class", "")
            if outer and outer in known_names:
                connected.add(name)
                connected.add(outer)

        suppressed = {
            cls["name"]
            for cls in all_classes
            if _SUPPRESSION_ANNOTATIONS & set(cls.get("annotations", []))
        }
        orphans = sorted(known_names - connected - suppressed)

        findings: list[Finding] = []
        for orphan_name in orphans:
            file_path = class_file.get(orphan_name, "unknown")
            cls_data = next(c for c in all_classes if c["name"] == orphan_name)
            line = cls_data.get("line", 0)
            findings.append(
                make_finding(
                    rule_id=self.id,
                    hit=Hit(
                        rag="amber",
                        severity="medium",
                        summary=(
                            f"Class '{orphan_name}' has no relationships with other classes"
                        ),
                        recommendation=(
                            "Investigate whether this class is dormant/dead code. "
                            "If still needed, ensure it is connected via inheritance, "
                            "composition, or usage in method signatures."
                        ),
                        locator=f"{file_path}:{line}",
                    ),
                    ev=relevant[0],
                    pattern_tag=self.pattern_tag,
                    default_confidence=self.default_confidence,
                ),
            )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "cpp-no-dormant-classes",
                    relevant[0],
                    summary="All classes are connected — no dormant classes detected.",
                    confidence=0.8,
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


__all__ = ["CppDormantClassesRule"]
