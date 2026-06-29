# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for architecture baseline save/load and CLI integration."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from nfr_review.structurizr_diff import (
    diff_workspaces,
    findings_from_drift,
    load_arch_baseline,
    save_arch_baseline,
)
from nfr_review.structurizr_models import (
    DslElement,
    DslModel,
    DslRelationship,
    DslWorkspace,
)


def _ws(name: str = "test", **model_kw: object) -> DslWorkspace:
    return DslWorkspace(name=name, model=DslModel(**model_kw))


class TestBaselineRoundtrip:
    def test_save_load_roundtrip(self, tmp_path: Path) -> None:
        ws = _ws(
            "MyApp",
            software_systems=[
                DslElement(
                    identifier="api",
                    element_type="softwareSystem",
                    name="API Gateway",
                    technology="Python",
                    description="Main API",
                )
            ],
            relationships=[
                DslRelationship(
                    source_id="api",
                    destination_id="db",
                    description="reads from",
                    technology="SQL",
                )
            ],
        )
        bl_path = tmp_path / "baseline.json"
        save_arch_baseline(ws, bl_path)
        assert bl_path.exists()

        loaded = load_arch_baseline(bl_path)
        assert loaded.name == "MyApp"
        assert len(loaded.model.software_systems) == 1
        assert loaded.model.software_systems[0].identifier == "api"
        assert loaded.model.software_systems[0].technology == "Python"
        assert len(loaded.model.relationships) == 1
        assert loaded.model.relationships[0].description == "reads from"

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        ws = _ws("Simple")
        nested = tmp_path / "a" / "b" / "c" / "baseline.json"
        save_arch_baseline(ws, nested)
        assert nested.exists()

    def test_load_missing_file_raises(self, tmp_path: Path) -> None:
        import pytest

        with pytest.raises(FileNotFoundError):
            load_arch_baseline(tmp_path / "does-not-exist.json")

    def test_roundtrip_preserves_drift_detection(self, tmp_path: Path) -> None:
        baseline = _ws(
            "v1",
            software_systems=[
                DslElement(
                    identifier="svc",
                    element_type="softwareSystem",
                    name="Service",
                )
            ],
        )
        scan = _ws(
            "v2",
            software_systems=[
                DslElement(
                    identifier="svc",
                    element_type="softwareSystem",
                    name="Service",
                ),
                DslElement(
                    identifier="newSvc",
                    element_type="softwareSystem",
                    name="New Service",
                ),
            ],
        )
        bl_path = tmp_path / "baseline.json"
        save_arch_baseline(baseline, bl_path)
        loaded = load_arch_baseline(bl_path)

        report = diff_workspaces(loaded, scan)
        assert report.has_drift
        added = [f for f in report.findings if f.kind == "element_added"]
        assert len(added) == 1
        assert added[0].element_id == "newSvc"

        findings = findings_from_drift(report, str(bl_path))
        assert len(findings) >= 1
        assert findings[0].rule_id == "arch-drift"


class TestArchCLIBaseline:
    def test_arch_help_shows_baseline_option(self) -> None:
        from nfr_review.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["arch", "--help"])
        assert result.exit_code == 0
        assert "--arch-baseline-dir" in result.output
