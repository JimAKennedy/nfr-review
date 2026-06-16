# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Detect classes/structs with zero relationships (Java, Python, Go).

Same algorithm as CPP-DORMANT but parameterized for Java, Python, and Go.
A class/struct with no inheritance, no field-type references, no parameter/
return-type dependencies, and no nesting is architecturally orphaned.
"""

from __future__ import annotations

import re
from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import make_green_finding

_TOKEN_RE = re.compile(r"\b([A-Za-z_]\w*)\b")

_JAVA_TYPE_NOISE = frozenset(
    {
        "void",
        "int",
        "long",
        "double",
        "float",
        "boolean",
        "char",
        "byte",
        "short",
        "String",
        "Object",
        "Integer",
        "Long",
        "Double",
        "Float",
        "Boolean",
        "Character",
        "Byte",
        "Short",
        "List",
        "Set",
        "Map",
        "Collection",
        "Iterator",
        "Optional",
        "Stream",
        "Iterable",
        "Comparable",
        "Serializable",
        "HashMap",
        "ArrayList",
        "HashSet",
        "TreeMap",
        "LinkedList",
        "Arrays",
        "Collections",
        "Class",
        "Enum",
        "Override",
        "Deprecated",
        "var",
    },
)

_PYTHON_TYPE_NOISE = frozenset(
    {
        "int",
        "float",
        "str",
        "bool",
        "bytes",
        "list",
        "dict",
        "set",
        "tuple",
        "frozenset",
        "None",
        "type",
        "object",
        "Any",
        "Optional",
        "Union",
        "Callable",
        "Iterator",
        "Generator",
        "Sequence",
        "Mapping",
        "MutableMapping",
        "MutableSequence",
        "Type",
        "ClassVar",
        "Final",
        "Protocol",
        "Self",
        "ABC",
        "abstractmethod",
        "dataclass",
        "field",
        "property",
    },
)

_GO_TYPE_NOISE = frozenset(
    {
        "int",
        "int8",
        "int16",
        "int32",
        "int64",
        "uint",
        "uint8",
        "uint16",
        "uint32",
        "uint64",
        "float32",
        "float64",
        "complex64",
        "complex128",
        "string",
        "bool",
        "byte",
        "rune",
        "error",
        "interface",
        "struct",
        "map",
        "chan",
        "func",
        "any",
        "comparable",
        "context",
        "Context",
        "sync",
        "Mutex",
        "WaitGroup",
        "Reader",
        "Writer",
        "Request",
        "Response",
        "ResponseWriter",
    },
)


def _type_refs(type_str: str, known: set[str], noise: frozenset[str]) -> set[str]:
    if not type_str:
        return set()
    return {tok for tok in _TOKEN_RE.findall(type_str) if tok in known and tok not in noise}


def _detect_orphans(
    evidence: list[Evidence],
    *,
    evidence_kind: str,
    classes_key: str,
    noise: frozenset[str],
    rule_id: str,
    pattern_tag_prefix: str,
) -> RuleResult:
    lang_ev = [e for e in evidence if e.kind == evidence_kind]
    if not lang_ev:
        return RuleResult(
            rule_id=rule_id, skipped=True, skip_reason=f"no {evidence_kind} evidence available"
        )

    all_classes: list[Any] = []
    class_file: dict[str, str] = {}
    for ev in lang_ev:
        for cls in getattr(ev.payload, classes_key, []):
            name = cls.name
            if name:
                all_classes.append(cls)
                class_file[name] = ev.payload.file_path

    if len(all_classes) < 2:
        return RuleResult(rule_id=rule_id, findings=[])

    known_names = {c.name for c in all_classes}
    connected: set[str] = set()

    for cls in all_classes:
        name = cls.name

        for base in cls.base_classes:
            base_name = base.name
            if base_name in known_names:
                connected.add(name)
                connected.add(base_name)

        for field in cls.fields:
            for ref in _type_refs(field.type, known_names, noise):
                if ref != name:
                    connected.add(name)
                    connected.add(ref)

        for method in cls.methods:
            for type_str in [method.return_type] + [p.type for p in method.parameters]:
                for ref in _type_refs(type_str, known_names, noise):
                    if ref != name:
                        connected.add(name)
                        connected.add(ref)

        for friend_name in getattr(cls, "friends", []):
            if friend_name in known_names and friend_name != name:
                connected.add(name)
                connected.add(friend_name)

        outer = cls.outer_class
        if outer and outer in known_names:
            connected.add(name)
            connected.add(outer)

    orphans = sorted(known_names - connected)

    findings: list[Finding] = []
    for orphan_name in orphans:
        file_path = class_file.get(orphan_name, "unknown")
        cls_data = next(c for c in all_classes if c.name == orphan_name)
        line = cls_data.line
        findings.append(
            Finding(
                rule_id=rule_id,
                rag="amber",
                severity="medium",
                summary=f"Class '{orphan_name}' has no relationships with other classes",
                recommendation=(
                    "Investigate whether this class is dormant/dead code. "
                    "If still needed, ensure it is connected via inheritance, "
                    "composition, or usage in method signatures."
                ),
                evidence_locator=f"{file_path}:{line}",
                collector_name=lang_ev[0].collector_name,
                collector_version=lang_ev[0].collector_version,
                confidence=0.7,
                pattern_tag=f"{pattern_tag_prefix}-dormant-class",
            ),
        )

    if not findings:
        findings.append(
            make_green_finding(
                rule_id,
                f"{pattern_tag_prefix}-no-dormant-classes",
                lang_ev[0],
                summary="All classes are connected — no dormant classes detected.",
                confidence=0.8,
            ),
        )

    return RuleResult(rule_id=rule_id, findings=findings)


class JavaDormantClassesRule:
    id = "java-dormant-classes"
    band: Band = 2
    required_collectors: list[str] = ["java-ast"]
    required_tech: list[str] = ["java"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        return _detect_orphans(
            evidence,
            evidence_kind="java-ast-file",
            classes_key="classes",
            noise=_JAVA_TYPE_NOISE,
            rule_id=self.id,
            pattern_tag_prefix="java",
        )


class PythonDormantClassesRule:
    id = "python-dormant-classes"
    band: Band = 2
    required_collectors: list[str] = ["python-ast"]
    required_tech: list[str] = ["python"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        return _detect_orphans(
            evidence,
            evidence_kind="python-ast-file",
            classes_key="classes",
            noise=_PYTHON_TYPE_NOISE,
            rule_id=self.id,
            pattern_tag_prefix="python",
        )


class GoDormantClassesRule:
    id = "go-dormant-classes"
    band: Band = 2
    required_collectors: list[str] = ["go-ast"]
    required_tech: list[str] = ["go"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        return _detect_orphans(
            evidence,
            evidence_kind="go-ast-file",
            classes_key="structs",
            noise=_GO_TYPE_NOISE,
            rule_id=self.id,
            pattern_tag_prefix="go",
        )


def _register() -> None:
    _rules: list[
        type[JavaDormantClassesRule | PythonDormantClassesRule | GoDormantClassesRule]
    ] = [
        JavaDormantClassesRule,
        PythonDormantClassesRule,
        GoDormantClassesRule,
    ]
    for cls in _rules:
        if cls.id not in rule_registry:
            rule_registry.register(cls.id, cls())


_register()

__all__ = ["JavaDormantClassesRule", "PythonDormantClassesRule", "GoDormantClassesRule"]
