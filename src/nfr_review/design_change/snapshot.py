# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nfr_review.design_change.models import (
    BASELINE_FORMAT_VERSION,
    StructuralBaseline,
)
from nfr_review.models import normalise_locator

# Set-metric items with this prefix carry a repo-relative file path.
_FILE_ITEM_PREFIX = "file:"


def _normalise_file_items(data: dict[str, Any]) -> None:
    """Rewrite ``file:`` set-metric items recorded with ``\\`` to use ``/``.

    Baselines saved by Windows runs before paths were normalised hold
    backslash paths; without this, every such item reads as removed and
    re-added on the next diff.
    """
    for category in (data.get("metrics") or {}).values():
        for metric in (category.get("set_metrics") or {}).values():
            metric["items"] = [
                normalise_locator(item) if item.startswith(_FILE_ITEM_PREFIX) else item
                for item in metric.get("items", [])
            ]


def save_baseline(baseline: StructuralBaseline, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = baseline.model_dump(mode="json")
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_baseline(path: Path) -> StructuralBaseline:
    if not path.exists():
        raise FileNotFoundError(f"structural baseline file not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    version = data.get("version", 0)
    if version > BASELINE_FORMAT_VERSION:
        raise ValueError(
            f"unsupported structural baseline version {version} "
            f"(max supported: {BASELINE_FORMAT_VERSION})"
        )

    _normalise_file_items(data)
    return StructuralBaseline.model_validate(data)
