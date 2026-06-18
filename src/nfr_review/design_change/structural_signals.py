# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""MetricExtractor implementations for structural and JDepend signals."""

from __future__ import annotations

from nfr_review.design_change.extractors import extractor_registry
from nfr_review.design_change.models import MetricCategory, NumericMetric, SetMetric
from nfr_review.models import Evidence

_AST_KINDS = frozenset(
    {
        "java-ast-file",
        "python-ast-file",
        "go-ast-file",
        "cpp-ast-file",
    }
)


class StructuralMetricsExtractor:
    """Extracts class-count and dormant-class-count from multi-language AST evidence."""

    @property
    def category(self) -> str:
        return "structure"

    def extract(self, evidence: list[Evidence]) -> MetricCategory:
        ast_evidence = [e for e in evidence if e.kind in _AST_KINDS]
        if not ast_evidence:
            return MetricCategory(category=self.category)

        # Gather all classes across all languages.
        # Each entry: (name, base_classes_list, outer_class_str)
        all_entries: list[tuple[str, list[str], str]] = []

        for ev in ast_evidence:
            payload = ev.payload
            if ev.kind in ("java-ast-file", "python-ast-file"):
                classes = getattr(payload, "classes", [])
                for cls in classes:
                    name = cls.name or ""
                    if not name:
                        continue
                    bases = [b.name for b in cls.base_classes if b.name]
                    outer = cls.outer_class or ""
                    all_entries.append((name, bases, outer))
            elif ev.kind == "go-ast-file":
                structs = getattr(payload, "structs", [])
                for s in structs:
                    name = s.name or ""
                    if not name:
                        continue
                    bases = [b.name for b in s.base_classes if b.name]
                    outer = s.outer_class or ""
                    all_entries.append((name, bases, outer))
            elif ev.kind == "cpp-ast-file":
                classes = getattr(payload, "classes", [])
                for cls in classes:
                    name = cls.name or ""
                    if not name:
                        continue
                    bases = [b.name for b in cls.base_classes if b.name]
                    outer = cls.outer_class or ""
                    all_entries.append((name, bases, outer))

        total = len(all_entries)

        # Simplified orphan heuristic: a class is connected if it:
        #   - has any base classes, OR
        #   - is referenced as a base by another class, OR
        #   - has an outer_class
        all_names: set[str] = {name for name, _, _ in all_entries}
        # Build set of names that appear as bases of other classes.
        all_base_names: set[str] = set()
        for _, bases, _ in all_entries:
            for b in bases:
                if b in all_names:
                    all_base_names.add(b)

        connected: set[str] = set()
        for name, bases, outer in all_entries:
            if bases:
                connected.add(name)
            if name in all_base_names:
                connected.add(name)
            if outer and outer in all_names:
                connected.add(name)

        dormant_count = total - len(connected)

        return MetricCategory(
            category=self.category,
            numeric_metrics={
                "class_count": NumericMetric(name="class_count", value=float(total)),
                "dormant_class_count": NumericMetric(
                    name="dormant_class_count", value=float(dormant_count)
                ),
            },
        )


class JDependMetricsExtractor:
    """Extracts instability and cycle metrics from JDepend evidence."""

    @property
    def category(self) -> str:
        return "jdepend"

    def extract(self, evidence: list[Evidence]) -> MetricCategory:
        packages_evidence = [e for e in evidence if e.kind == "jdepend-packages"]
        summary_evidence = [e for e in evidence if e.kind == "jdepend-summary"]

        if not packages_evidence and not summary_evidence:
            return MetricCategory(category=self.category)

        numeric_metrics: dict[str, NumericMetric] = {}
        set_metrics: dict[str, SetMetric] = {}

        # Max instability across all packages from all jdepend-packages evidence.
        if packages_evidence:
            max_i = 0.0
            for ev in packages_evidence:
                for pkg in ev.payload.packages:
                    if pkg.i > max_i:
                        max_i = pkg.i
            numeric_metrics["jdepend_instability"] = NumericMetric(
                name="jdepend_instability", value=max_i
            )

        # Flattened package names involved in cycles from jdepend-summary evidence.
        if summary_evidence:
            cycle_packages: set[str] = set()
            for ev in summary_evidence:
                for group in ev.payload.cycle_groups:
                    for pkg_name in group:
                        cycle_packages.add(pkg_name)
            set_metrics["jdepend_cycles"] = SetMetric(
                name="jdepend_cycles", items=sorted(cycle_packages)
            )

        return MetricCategory(
            category=self.category,
            numeric_metrics=numeric_metrics,
            set_metrics=set_metrics,
        )


def _register() -> None:
    instances: list[StructuralMetricsExtractor | JDependMetricsExtractor] = [
        StructuralMetricsExtractor(),
        JDependMetricsExtractor(),
    ]
    for ext in instances:
        if ext.category not in extractor_registry:
            extractor_registry.register(ext.category, ext)


_register()

__all__ = ["JDependMetricsExtractor", "StructuralMetricsExtractor"]
