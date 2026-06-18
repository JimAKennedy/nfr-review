# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from nfr_review.design_change.models import StructuralBaseline


class NumericDelta(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    old_value: float
    new_value: float
    delta: float
    pct_change: float | None = None


class SetDelta(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)


class CategoryDiff(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    category: str
    numeric_deltas: list[NumericDelta] = Field(default_factory=list)
    set_deltas: list[SetDelta] = Field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.numeric_deltas or self.set_deltas)


def diff_baselines(
    previous: StructuralBaseline,
    current: StructuralBaseline,
) -> dict[str, CategoryDiff]:
    all_categories = set(previous.metrics) | set(current.metrics)
    result: dict[str, CategoryDiff] = {}

    for cat_name in sorted(all_categories):
        prev_cat = previous.metrics.get(cat_name)
        curr_cat = current.metrics.get(cat_name)

        numeric_deltas: list[NumericDelta] = []
        set_deltas: list[SetDelta] = []

        prev_numeric = prev_cat.numeric_metrics if prev_cat else {}
        curr_numeric = curr_cat.numeric_metrics if curr_cat else {}
        all_numeric = set(prev_numeric) | set(curr_numeric)

        for metric_name in sorted(all_numeric):
            old_val = prev_numeric[metric_name].value if metric_name in prev_numeric else 0.0
            new_val = curr_numeric[metric_name].value if metric_name in curr_numeric else 0.0
            delta = new_val - old_val
            if delta == 0.0:
                continue
            pct = (delta / old_val * 100.0) if old_val != 0.0 else None
            numeric_deltas.append(
                NumericDelta(
                    name=metric_name,
                    old_value=old_val,
                    new_value=new_val,
                    delta=delta,
                    pct_change=pct,
                )
            )

        prev_sets = prev_cat.set_metrics if prev_cat else {}
        curr_sets = curr_cat.set_metrics if curr_cat else {}
        all_sets = set(prev_sets) | set(curr_sets)

        for metric_name in sorted(all_sets):
            old_items = (
                prev_sets[metric_name].item_set if metric_name in prev_sets else frozenset()
            )
            new_items = (
                curr_sets[metric_name].item_set if metric_name in curr_sets else frozenset()
            )
            added = sorted(new_items - old_items)
            removed = sorted(old_items - new_items)
            if not added and not removed:
                continue
            set_deltas.append(SetDelta(name=metric_name, added=added, removed=removed))

        cat_diff = CategoryDiff(
            category=cat_name,
            numeric_deltas=numeric_deltas,
            set_deltas=set_deltas,
        )
        if cat_diff.has_changes:
            result[cat_name] = cat_diff

    return result


def apply_thresholds(
    diffs: dict[str, CategoryDiff],
    thresholds: dict[str, float],
) -> dict[str, CategoryDiff]:
    """Filter diffs, keeping only changes that exceed configured thresholds.

    For numeric deltas: the threshold is the minimum absolute pct_change (%).
    If pct_change is None (zero-base), the delta always passes.
    Threshold lookup: tries "<metric_name>" in the thresholds dict.
    If no matching threshold, the delta passes through unfiltered.

    For set deltas: the threshold is the minimum total count of (added + removed).
    Threshold lookup uses "<metric_name>".
    If no matching threshold, the delta passes through unfiltered.
    """
    result: dict[str, CategoryDiff] = {}

    for cat_name, cat_diff in diffs.items():
        filtered_numeric = [
            nd
            for nd in cat_diff.numeric_deltas
            if nd.name not in thresholds
            or nd.pct_change is None
            or abs(nd.pct_change) >= thresholds[nd.name]
        ]
        filtered_sets = [
            sd
            for sd in cat_diff.set_deltas
            if sd.name not in thresholds
            or len(sd.added) + len(sd.removed) >= thresholds[sd.name]
        ]
        filtered_cat = CategoryDiff(
            category=cat_name,
            numeric_deltas=filtered_numeric,
            set_deltas=filtered_sets,
        )
        if filtered_cat.has_changes:
            result[cat_name] = filtered_cat

    return result


def format_diff_summary(diffs: dict[str, CategoryDiff]) -> str:
    if not diffs:
        return "No structural changes detected."

    lines: list[str] = ["Design Change Summary", "=" * 21]

    for cat_name in sorted(diffs):
        diff = diffs[cat_name]
        lines.append(f"\n[{cat_name}]")

        for nd in diff.numeric_deltas:
            pct_str = f" ({nd.pct_change:+.1f}%)" if nd.pct_change is not None else ""
            val_str = f"{nd.old_value:.0f} -> {nd.new_value:.0f} ({nd.delta:+.0f})"
            lines.append(f"  {nd.name}: {val_str}{pct_str}")

        for sd in diff.set_deltas:
            if sd.added:
                lines.append(f"  {sd.name} added: {', '.join(sd.added)}")
            if sd.removed:
                lines.append(f"  {sd.name} removed: {', '.join(sd.removed)}")

    return "\n".join(lines)
