# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: python-mutable-default — detects mutable default arguments in function definitions."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.python_ast import PythonAstFilePayload
from nfr_review.models import Evidence
from nfr_review.registry import rule_registry
from nfr_review.rules.framework import FieldRule, Hit

_MUTABLE_TYPES = frozenset({"list", "dict", "set"})


class PythonMutableDefaultRule(FieldRule[PythonAstFilePayload]):
    """Flag function definitions using mutable default arguments."""

    id = "python-mutable-default"
    collector_name = "python-ast"
    evidence_kind = "python-ast-file"
    payload_type = PythonAstFilePayload
    pattern_tag = "mutable-default"
    default_confidence = 0.9
    all_clear_summary = "No mutable default arguments detected."

    def check(self, payload: PythonAstFilePayload, ev: Evidence) -> Iterable[Hit]:
        for func in payload.functions:
            for default in func.default_args:
                if default.default_type in _MUTABLE_TYPES:
                    yield Hit(
                        rag="amber",
                        summary=(
                            f"Mutable default argument ({default.default_type})"
                            f" in {func.name}()"
                        ),
                        recommendation=(
                            "Use None as default and initialize in function body:"
                            " if arg is None: arg = []"
                        ),
                        locator=f"{payload.file_path}:{default.line}",
                    )


def _register() -> None:
    if "python-mutable-default" not in rule_registry:
        rule_registry.register("python-mutable-default", PythonMutableDefaultRule())


_register()

__all__ = ["PythonMutableDefaultRule"]
