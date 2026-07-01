"""Tests for dep-freshness rule: staleness graduation and dead library detection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from nfr_review.models import Evidence
from nfr_review.rules.dep_freshness import DepFreshnessRule, _reference_now

# ── helpers ──────────────────────────────────────────────────────────────


def _make_evidence(
    deps: list[dict],
    collector_name: str = "python-deps",
    kind: str = "python-deps",
) -> Evidence:
    return Evidence(
        collector_name=collector_name,
        collector_version="0.1.0",
        locator="test://dep-freshness",
        kind=kind,
        payload={"dependencies": deps},
    )


def _make_dep(
    name: str = "example-lib",
    declared_version: str = "1.0.0",
    latest_version: str | None = "1.0.0",
    latest_release_date: str | None = None,
    deps_dev_status: str = "ok",
) -> dict:
    dep: dict = {
        "name": name,
        "declared_version": declared_version,
        "deps_dev_status": deps_dev_status,
    }
    if latest_version is not None:
        dep["latest_version"] = latest_version
    if latest_release_date is not None:
        dep["latest_release_date"] = latest_release_date
    return dep


def _iso_days_ago(days: int) -> str:
    dt = datetime.now(UTC) - timedelta(days=days)
    return dt.isoformat()


# ── staleness graduation (R032) ──────────────────────────────────────────


class TestStalenessGraduation:
    def setup_method(self) -> None:
        self.rule = DepFreshnessRule()

    def test_patch_drift_green(self) -> None:
        ev = _make_evidence([_make_dep(declared_version="1.0.0", latest_version="1.0.3")])
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "green"
        assert f.severity == "info"
        assert f.pattern_tag == "stale-dep-patch"
        assert "patch" in f.summary

    def test_minor_drift_amber(self) -> None:
        ev = _make_evidence([_make_dep(declared_version="1.0.0", latest_version="1.2.0")])
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "amber"
        assert f.severity == "medium"
        assert f.pattern_tag == "stale-dep-minor"
        assert "minor" in f.summary

    def test_major_drift_red(self) -> None:
        ev = _make_evidence([_make_dep(declared_version="1.0.0", latest_version="2.0.0")])
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "red"
        assert f.severity == "high"
        assert f.pattern_tag == "stale-dep-major"
        assert "major" in f.summary

    def test_fresh_no_finding(self) -> None:
        ev = _make_evidence([_make_dep(declared_version="2.1.0", latest_version="2.1.0")])
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].pattern_tag == "dep-freshness-ok"


# ── dead library detection (R030) ────────────────────────────────────────


class TestDeadLibraryDetection:
    def setup_method(self) -> None:
        self.rule = DepFreshnessRule()

    def test_dead_library_amber(self) -> None:
        ev = _make_evidence(
            [
                _make_dep(
                    latest_release_date=_iso_days_ago(400),
                    declared_version="1.0.0",
                    latest_version="1.0.0",
                )
            ]
        )
        result = self.rule.evaluate([ev], None)
        dead_findings = [f for f in result.findings if f.pattern_tag == "dead-library"]
        assert len(dead_findings) == 1
        f = dead_findings[0]
        assert f.rag == "amber"
        assert f.severity == "medium"
        assert "no release" in f.summary.lower() or "abandoned" in f.summary.lower()

    def test_alive_library_no_finding(self) -> None:
        ev = _make_evidence(
            [
                _make_dep(
                    latest_release_date=_iso_days_ago(180),
                    declared_version="1.0.0",
                    latest_version="1.0.0",
                )
            ]
        )
        result = self.rule.evaluate([ev], None)
        dead_findings = [f for f in result.findings if f.pattern_tag == "dead-library"]
        assert len(dead_findings) == 0

    def test_boundary_365_days_not_dead(self) -> None:
        ev = _make_evidence(
            [
                _make_dep(
                    latest_release_date=_iso_days_ago(365),
                    declared_version="1.0.0",
                    latest_version="1.0.0",
                )
            ]
        )
        result = self.rule.evaluate([ev], None)
        dead_findings = [f for f in result.findings if f.pattern_tag == "dead-library"]
        assert len(dead_findings) == 0

    def test_boundary_366_days_dead(self) -> None:
        ev = _make_evidence(
            [
                _make_dep(
                    latest_release_date=_iso_days_ago(366),
                    declared_version="1.0.0",
                    latest_version="1.0.0",
                )
            ]
        )
        result = self.rule.evaluate([ev], None)
        dead_findings = [f for f in result.findings if f.pattern_tag == "dead-library"]
        assert len(dead_findings) == 1


# ── graceful handling ────────────────────────────────────────────────────


class TestGracefulHandling:
    def setup_method(self) -> None:
        self.rule = DepFreshnessRule()

    def test_skips_error_status(self) -> None:
        ev = _make_evidence(
            [
                _make_dep(
                    deps_dev_status="error",
                    declared_version="1.0.0",
                    latest_version="2.0.0",
                )
            ]
        )
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].pattern_tag == "dep-freshness-ok"

    def test_skips_not_found_status(self) -> None:
        ev = _make_evidence(
            [
                _make_dep(
                    deps_dev_status="not_found",
                    declared_version="1.0.0",
                    latest_version="2.0.0",
                )
            ]
        )
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].pattern_tag == "dep-freshness-ok"

    def test_unparseable_version_skipped(self) -> None:
        ev = _make_evidence(
            [
                _make_dep(
                    declared_version="*",
                    latest_version="2.0.0",
                    latest_release_date=_iso_days_ago(400),
                )
            ]
        )
        result = self.rule.evaluate([ev], None)
        staleness_findings = [
            f for f in result.findings if f.pattern_tag.startswith("stale-dep")
        ]
        assert len(staleness_findings) == 0
        dead_findings = [f for f in result.findings if f.pattern_tag == "dead-library"]
        assert len(dead_findings) == 1

    def test_unparseable_latest_version_skipped(self) -> None:
        ev = _make_evidence([_make_dep(declared_version="1.0.0", latest_version="latest")])
        result = self.rule.evaluate([ev], None)
        staleness_findings = [
            f for f in result.findings if f.pattern_tag.startswith("stale-dep")
        ]
        assert len(staleness_findings) == 0

    def test_missing_latest_version_skipped(self) -> None:
        ev = _make_evidence([_make_dep(declared_version="1.0.0", latest_version=None)])
        result = self.rule.evaluate([ev], None)
        staleness_findings = [
            f for f in result.findings if f.pattern_tag.startswith("stale-dep")
        ]
        assert len(staleness_findings) == 0

    def test_missing_release_date(self) -> None:
        ev = _make_evidence(
            [
                _make_dep(
                    declared_version="1.0.0",
                    latest_version="2.0.0",
                    latest_release_date=None,
                )
            ]
        )
        result = self.rule.evaluate([ev], None)
        dead_findings = [f for f in result.findings if f.pattern_tag == "dead-library"]
        assert len(dead_findings) == 0
        staleness_findings = [
            f for f in result.findings if f.pattern_tag.startswith("stale-dep")
        ]
        assert len(staleness_findings) == 1


# ── multi-ecosystem ──────────────────────────────────────────────────────


class TestMultiEcosystem:
    def setup_method(self) -> None:
        self.rule = DepFreshnessRule()

    def test_nodejs_deps_evidence(self) -> None:
        ev = _make_evidence(
            [_make_dep(name="express", declared_version="4.0.0", latest_version="5.0.0")],
            collector_name="nodejs-deps",
            kind="nodejs-deps",
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert any(f.pattern_tag == "stale-dep-major" for f in result.findings)
        assert result.findings[0].collector_name == "nodejs-deps"

    def test_java_deps_evidence(self) -> None:
        ev = _make_evidence(
            [_make_dep(name="guava", declared_version="30.0.0", latest_version="30.1.0")],
            collector_name="java-deps",
            kind="java-deps",
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert any(f.pattern_tag == "stale-dep-minor" for f in result.findings)

    def test_go_deps_evidence(self) -> None:
        ev = _make_evidence(
            [
                _make_dep(
                    name="golang.org/x/text", declared_version="0.9.0", latest_version="0.14.0"
                )
            ],
            collector_name="go-deps",
            kind="go-deps",
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert any(f.pattern_tag == "stale-dep-minor" for f in result.findings)

    def test_csharp_deps_evidence(self) -> None:
        ev = _make_evidence(
            [
                _make_dep(
                    name="Newtonsoft.Json", declared_version="12.0.0", latest_version="13.0.0"
                )
            ],
            collector_name="csharp-deps",
            kind="csharp-deps",
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert any(f.pattern_tag == "stale-dep-major" for f in result.findings)

    def test_mixed_ecosystems(self) -> None:
        ev_python = _make_evidence(
            [_make_dep(name="requests", declared_version="2.28.0", latest_version="2.31.0")],
            collector_name="python-deps",
            kind="python-deps",
        )
        ev_node = _make_evidence(
            [_make_dep(name="lodash", declared_version="3.0.0", latest_version="4.0.0")],
            collector_name="nodejs-deps",
            kind="nodejs-deps",
        )
        ev_java = _make_evidence(
            [_make_dep(name="jackson", declared_version="2.13.0", latest_version="2.15.0")],
            collector_name="java-deps",
            kind="java-deps",
        )
        result = self.rule.evaluate([ev_python, ev_node, ev_java], None)
        assert not result.skipped
        assert len(result.findings) == 3
        collectors = {f.collector_name for f in result.findings}
        assert collectors == {"python-deps", "nodejs-deps", "java-deps"}


# ── green fallback and skip ──────────────────────────────────────────────


class TestGreenFallbackAndSkip:
    def setup_method(self) -> None:
        self.rule = DepFreshnessRule()

    def test_all_fresh_emits_green(self) -> None:
        ev = _make_evidence(
            [
                _make_dep(name="a", declared_version="1.0.0", latest_version="1.0.0"),
                _make_dep(name="b", declared_version="3.2.1", latest_version="3.2.1"),
            ]
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "green"
        assert f.pattern_tag == "dep-freshness-ok"
        assert "up to date" in f.summary.lower()

    def test_no_evidence_skipped(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert result.skip_reason is not None
        assert "no dependency evidence" in result.skip_reason.lower()

    def test_unrelated_evidence_skipped(self) -> None:
        ev = Evidence(
            collector_name="security-scanner",
            collector_version="0.1.0",
            locator="test://other",
            kind="security-scan",
            payload={},
        )
        result = self.rule.evaluate([ev], None)
        assert result.skipped is True


# ── constraint stripping ─────────────────────────────────────────────────


class TestConstraintStripping:
    def setup_method(self) -> None:
        self.rule = DepFreshnessRule()

    def test_caret_constraint_stripped(self) -> None:
        ev = _make_evidence([_make_dep(declared_version="^1.0.0", latest_version="2.0.0")])
        result = self.rule.evaluate([ev], None)
        assert any(f.pattern_tag == "stale-dep-major" for f in result.findings)

    def test_tilde_constraint_stripped(self) -> None:
        ev = _make_evidence([_make_dep(declared_version="~=1.0.0", latest_version="1.2.0")])
        result = self.rule.evaluate([ev], None)
        assert any(f.pattern_tag == "stale-dep-minor" for f in result.findings)

    def test_gte_constraint_stripped(self) -> None:
        ev = _make_evidence([_make_dep(declared_version=">=1.0.0", latest_version="1.0.3")])
        result = self.rule.evaluate([ev], None)
        assert any(f.pattern_tag == "stale-dep-patch" for f in result.findings)


# ── NFR_REFERENCE_DATE env var ──────────────────────────────────────────


class TestReferenceDate:
    def test_env_var_overrides_now(self, monkeypatch: pytest.MonkeyPatch) -> None:
        frozen = "2025-06-15T12:00:00+00:00"
        monkeypatch.setenv("NFR_REFERENCE_DATE", frozen)
        result = _reference_now()
        assert result == datetime.fromisoformat(frozen)

    def test_falls_back_to_now(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NFR_REFERENCE_DATE", raising=False)
        before = datetime.now(UTC)
        result = _reference_now()
        after = datetime.now(UTC)
        assert before <= result <= after

    def test_frozen_time_prevents_dead_library_drift(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NFR_REFERENCE_DATE", "2025-06-15T00:00:00+00:00")
        rule = DepFreshnessRule()
        ev = _make_evidence(
            [
                _make_dep(
                    latest_release_date="2024-07-01T00:00:00+00:00",
                    declared_version="1.0.0",
                    latest_version="1.0.0",
                )
            ]
        )
        result = rule.evaluate([ev], None)
        dead = [f for f in result.findings if f.pattern_tag == "dead-library"]
        assert len(dead) == 0

        monkeypatch.setenv("NFR_REFERENCE_DATE", "2025-08-01T00:00:00+00:00")
        result2 = rule.evaluate([ev], None)
        dead2 = [f for f in result2.findings if f.pattern_tag == "dead-library"]
        assert len(dead2) == 1
