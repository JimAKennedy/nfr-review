# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
from pathlib import Path

from nfr_review.design_change.models import (
    BASELINE_FORMAT_VERSION,
    StructuralBaseline,
)


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

    return StructuralBaseline.model_validate(data)
