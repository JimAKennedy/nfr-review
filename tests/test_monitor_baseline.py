# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for InteractionBaseline model and serialization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nfr_review.monitor.baseline import (
    BASELINE_FORMAT_VERSION,
    InteractionBaseline,
    diff_baselines,
    load_baseline,
    save_baseline,
)
from nfr_review.monitor.fingerprint import InteractionFingerprint


def _fp(
    caller: str = "a",
    callee: str = "b",
    op: str = "GET /x",
    kind: int = 3,
    proto: str = "http",
) -> InteractionFingerprint:
    return InteractionFingerprint(
        caller_service=caller,
        callee_service=callee,
        operation=op,
        span_kind=kind,
        protocol=proto,
    )


class TestInteractionBaseline:
    def test_create_with_defaults(self) -> None:
        bl = InteractionBaseline()
        assert bl.version == BASELINE_FORMAT_VERSION
        assert bl.fingerprints == []
        assert bl.created_at

    def test_fingerprint_set(self) -> None:
        fp1 = _fp(op="GET /a")
        fp2 = _fp(op="GET /b")
        bl = InteractionBaseline(fingerprints=[fp1, fp2, fp1])
        assert len(bl.fingerprint_set) == 2

    def test_fingerprint_hashes(self) -> None:
        fp = _fp()
        bl = InteractionBaseline(fingerprints=[fp])
        assert fp.fingerprint_hash in bl.fingerprint_hashes


class TestSaveLoadRoundTrip:
    def test_round_trip(self, tmp_path: Path) -> None:
        fp1 = _fp(op="GET /orders")
        fp2 = _fp(caller="x", callee="y", op="INSERT", kind=3, proto="db")
        original = InteractionBaseline(
            source="uat-traces.ndjson",
            trace_count=10,
            span_count=200,
            fingerprints=[fp1, fp2],
        )
        out = tmp_path / "baseline.json"
        save_baseline(original, out)
        loaded = load_baseline(out)

        assert loaded.version == original.version
        assert loaded.source == original.source
        assert loaded.trace_count == original.trace_count
        assert loaded.span_count == original.span_count
        assert len(loaded.fingerprints) == 2
        assert loaded.fingerprint_set == original.fingerprint_set

    def test_file_is_valid_json(self, tmp_path: Path) -> None:
        bl = InteractionBaseline(fingerprints=[_fp()])
        out = tmp_path / "bl.json"
        save_baseline(bl, out)
        data = json.loads(out.read_text())
        assert data["version"] == BASELINE_FORMAT_VERSION
        assert isinstance(data["fingerprints"], list)

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        out = tmp_path / "sub" / "dir" / "bl.json"
        save_baseline(InteractionBaseline(), out)
        assert out.exists()


class TestLoadValidation:
    def test_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_baseline(tmp_path / "nope.json")

    def test_unsupported_version(self, tmp_path: Path) -> None:
        out = tmp_path / "future.json"
        out.write_text(json.dumps({"version": 999, "fingerprints": []}))
        with pytest.raises(ValueError, match="unsupported baseline version"):
            load_baseline(out)

    def test_current_version_accepted(self, tmp_path: Path) -> None:
        out = tmp_path / "ok.json"
        bl = InteractionBaseline(fingerprints=[_fp()])
        save_baseline(bl, out)
        loaded = load_baseline(out)
        assert loaded.version == BASELINE_FORMAT_VERSION


class TestDiffBaselines:
    def test_novel_interactions(self) -> None:
        bl = InteractionBaseline(fingerprints=[_fp(op="GET /a")])
        observed = {_fp(op="GET /a"), _fp(op="GET /b")}
        novel, disappeared = diff_baselines(bl, observed)
        assert len(novel) == 1
        assert next(iter(novel)).operation == "GET /b"
        assert len(disappeared) == 0

    def test_disappeared_interactions(self) -> None:
        bl = InteractionBaseline(fingerprints=[_fp(op="GET /a"), _fp(op="GET /b")])
        observed = {_fp(op="GET /a")}
        novel, disappeared = diff_baselines(bl, observed)
        assert len(novel) == 0
        assert len(disappeared) == 1
        assert next(iter(disappeared)).operation == "GET /b"

    def test_identical(self) -> None:
        fp = _fp()
        bl = InteractionBaseline(fingerprints=[fp])
        novel, disappeared = diff_baselines(bl, {fp})
        assert len(novel) == 0
        assert len(disappeared) == 0

    def test_empty_baseline(self) -> None:
        bl = InteractionBaseline()
        observed = {_fp()}
        novel, disappeared = diff_baselines(bl, observed)
        assert len(novel) == 1
        assert len(disappeared) == 0
