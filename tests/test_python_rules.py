"""Tests for the 4 Python-specific NFR rules."""

from __future__ import annotations

from nfr_review.models import Evidence
from nfr_review.registry import rule_registry
from nfr_review.rules.python_async_fire_forget import PythonAsyncFireForgetRule
from nfr_review.rules.python_broad_except_silent import PythonBroadExceptSilentRule
from nfr_review.rules.python_mutable_default import PythonMutableDefaultRule
from nfr_review.rules.python_star_import import PythonStarImportRule

_COLLECTOR = "python-ast"
_VERSION = "0.1.0"
_KIND = "python-ast-file"

_R007_FIELDS = {
    "rule_id",
    "rag",
    "severity",
    "summary",
    "recommendation",
    "evidence_locator",
    "collector_name",
    "collector_version",
    "confidence",
    "pattern_tag",
    "content_hash",
    "origin",
}


def _make_evidence(payload: dict, locator: str = "test.py") -> Evidence:
    return Evidence(
        collector_name=_COLLECTOR,
        collector_version=_VERSION,
        locator=locator,
        kind=_KIND,
        payload={"file_path": locator, **payload},
    )


def _non_python_evidence() -> list[Evidence]:
    return [
        Evidence(
            collector_name="java-ast",
            collector_version="0.1.0",
            locator="Main.java",
            kind="java-ast-file",
            payload={},
        )
    ]


# ---------------------------------------------------------------------------
# python-mutable-default
# ---------------------------------------------------------------------------


class TestMutableDefaultRule:
    rule = PythonMutableDefaultRule()

    def test_detects_list_default(self) -> None:
        ev = _make_evidence(
            {
                "functions": [
                    {
                        "name": "foo",
                        "line": 1,
                        "is_async": False,
                        "decorators": [],
                        "default_args": [{"name": "items", "default_type": "list", "line": 1}],
                    }
                ]
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert result.findings[0].pattern_tag == "mutable-default"

    def test_detects_dict_and_set_defaults(self) -> None:
        ev = _make_evidence(
            {
                "functions": [
                    {
                        "name": "bar",
                        "line": 5,
                        "is_async": False,
                        "decorators": [],
                        "default_args": [
                            {"name": "mapping", "default_type": "dict", "line": 5},
                            {"name": "unique", "default_type": "set", "line": 5},
                        ],
                    }
                ]
            }
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 2

    def test_green_on_clean_code(self) -> None:
        ev = _make_evidence(
            {
                "functions": [
                    {
                        "name": "ok",
                        "line": 1,
                        "is_async": False,
                        "decorators": [],
                        "default_args": [{"name": "x", "default_type": "other", "line": 1}],
                    }
                ]
            }
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_skipped_without_python_evidence(self) -> None:
        result = self.rule.evaluate(_non_python_evidence(), None)
        assert result.skipped
        assert "no python-ast evidence" in (result.skip_reason or "")

    def test_r007_fields(self) -> None:
        ev = _make_evidence(
            {
                "functions": [
                    {
                        "name": "f",
                        "line": 3,
                        "is_async": False,
                        "decorators": [],
                        "default_args": [{"name": "a", "default_type": "list", "line": 3}],
                    }
                ]
            }
        )
        result = self.rule.evaluate([ev], None)
        finding = result.findings[0]
        assert set(finding.model_dump().keys()) == _R007_FIELDS


# ---------------------------------------------------------------------------
# python-star-import
# ---------------------------------------------------------------------------


class TestStarImportRule:
    rule = PythonStarImportRule()

    def test_detects_star_import(self) -> None:
        ev = _make_evidence(
            {"imports": [{"module": "os", "names": [], "is_star": True, "line": 1}]}
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert result.findings[0].pattern_tag == "star-import"
        assert "os" in result.findings[0].summary

    def test_green_on_explicit_imports(self) -> None:
        ev = _make_evidence(
            {"imports": [{"module": "os", "names": ["path"], "is_star": False, "line": 1}]}
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_skipped_without_python_evidence(self) -> None:
        result = self.rule.evaluate(_non_python_evidence(), None)
        assert result.skipped

    def test_multiple_star_imports(self) -> None:
        ev = _make_evidence(
            {
                "imports": [
                    {"module": "os", "names": [], "is_star": True, "line": 1},
                    {"module": "sys", "names": [], "is_star": True, "line": 2},
                    {"module": "json", "names": ["loads"], "is_star": False, "line": 3},
                ]
            }
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 2

    def test_r007_fields(self) -> None:
        ev = _make_evidence(
            {"imports": [{"module": "os", "names": [], "is_star": True, "line": 1}]}
        )
        result = self.rule.evaluate([ev], None)
        assert set(result.findings[0].model_dump().keys()) == _R007_FIELDS


# ---------------------------------------------------------------------------
# python-broad-except-silent
# ---------------------------------------------------------------------------


class TestBroadExceptSilentRule:
    rule = PythonBroadExceptSilentRule()

    def test_detects_silent_exception_catch(self) -> None:
        ev = _make_evidence(
            {
                "catch_blocks": [
                    {
                        "caught_type": "Exception",
                        "rethrows": False,
                        "has_logging": False,
                        "line": 10,
                        "file": "test.py",
                    }
                ]
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "red"
        assert result.findings[0].severity == "high"
        assert result.findings[0].pattern_tag == "broad-except-silent"

    def test_detects_silent_base_exception(self) -> None:
        ev = _make_evidence(
            {
                "catch_blocks": [
                    {
                        "caught_type": "BaseException",
                        "rethrows": False,
                        "has_logging": False,
                        "line": 5,
                        "file": "test.py",
                    }
                ]
            }
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "red"

    def test_green_when_rethrows(self) -> None:
        ev = _make_evidence(
            {
                "catch_blocks": [
                    {
                        "caught_type": "Exception",
                        "rethrows": True,
                        "has_logging": False,
                        "line": 10,
                        "file": "test.py",
                    }
                ]
            }
        )
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "green"

    def test_green_when_has_logging(self) -> None:
        ev = _make_evidence(
            {
                "catch_blocks": [
                    {
                        "caught_type": "Exception",
                        "rethrows": False,
                        "has_logging": True,
                        "line": 10,
                        "file": "test.py",
                    }
                ]
            }
        )
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "green"

    def test_ignores_specific_exceptions(self) -> None:
        ev = _make_evidence(
            {
                "catch_blocks": [
                    {
                        "caught_type": "ValueError",
                        "rethrows": False,
                        "has_logging": False,
                        "line": 10,
                        "file": "test.py",
                    }
                ]
            }
        )
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "green"

    def test_skipped_without_python_evidence(self) -> None:
        result = self.rule.evaluate(_non_python_evidence(), None)
        assert result.skipped

    def test_r007_fields(self) -> None:
        ev = _make_evidence(
            {
                "catch_blocks": [
                    {
                        "caught_type": "Exception",
                        "rethrows": False,
                        "has_logging": False,
                        "line": 1,
                        "file": "test.py",
                    }
                ]
            }
        )
        result = self.rule.evaluate([ev], None)
        assert set(result.findings[0].model_dump().keys()) == _R007_FIELDS


# ---------------------------------------------------------------------------
# python-async-fire-and-forget
# ---------------------------------------------------------------------------


class TestAsyncFireForgetRule:
    rule = PythonAsyncFireForgetRule()

    def test_detects_unstored_create_task(self) -> None:
        ev = _make_evidence(
            {"async_calls": [{"call": "asyncio.create_task", "line": 7, "stored": False}]}
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert result.findings[0].pattern_tag == "async-fire-and-forget"

    def test_green_when_task_stored(self) -> None:
        ev = _make_evidence(
            {"async_calls": [{"call": "asyncio.create_task", "line": 7, "stored": True}]}
        )
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "green"

    def test_skipped_without_python_evidence(self) -> None:
        result = self.rule.evaluate(_non_python_evidence(), None)
        assert result.skipped

    def test_multiple_fire_and_forget(self) -> None:
        ev = _make_evidence(
            {
                "async_calls": [
                    {"call": "asyncio.create_task", "line": 3, "stored": False},
                    {"call": "asyncio.ensure_future", "line": 8, "stored": False},
                    {"call": "asyncio.create_task", "line": 12, "stored": True},
                ]
            }
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 2

    def test_r007_fields(self) -> None:
        ev = _make_evidence(
            {"async_calls": [{"call": "asyncio.create_task", "line": 1, "stored": False}]}
        )
        result = self.rule.evaluate([ev], None)
        assert set(result.findings[0].model_dump().keys()) == _R007_FIELDS


# ---------------------------------------------------------------------------
# Multi-file aggregation (shared across rules)
# ---------------------------------------------------------------------------


class TestMultiFileAggregation:
    def test_mutable_default_across_files(self) -> None:
        ev1 = _make_evidence(
            {
                "functions": [
                    {
                        "name": "a",
                        "line": 1,
                        "is_async": False,
                        "decorators": [],
                        "default_args": [{"name": "x", "default_type": "list", "line": 1}],
                    }
                ]
            },
            locator="a.py",
        )
        ev2 = _make_evidence(
            {
                "functions": [
                    {
                        "name": "b",
                        "line": 5,
                        "is_async": False,
                        "decorators": [],
                        "default_args": [{"name": "y", "default_type": "dict", "line": 5}],
                    }
                ]
            },
            locator="b.py",
        )
        result = PythonMutableDefaultRule().evaluate([ev1, ev2], None)
        assert len(result.findings) == 2
        locators = {f.evidence_locator for f in result.findings}
        assert "a.py:1" in locators
        assert "b.py:5" in locators

    def test_star_import_across_files(self) -> None:
        ev1 = _make_evidence(
            {"imports": [{"module": "os", "names": [], "is_star": True, "line": 1}]},
            locator="x.py",
        )
        ev2 = _make_evidence(
            {"imports": [{"module": "sys", "names": [], "is_star": True, "line": 2}]},
            locator="y.py",
        )
        result = PythonStarImportRule().evaluate([ev1, ev2], None)
        assert len(result.findings) == 2


# ---------------------------------------------------------------------------
# Registry verification
# ---------------------------------------------------------------------------


class TestRegistryPresence:
    def test_all_python_rules_registered(self) -> None:
        import nfr_review.rules  # noqa: F401 — triggers auto-registration

        expected = [
            "python-mutable-default",
            "python-star-import",
            "python-broad-except-silent",
            "python-async-fire-and-forget",
        ]
        registered = rule_registry.ids()
        for rule_id in expected:
            assert rule_id in registered, f"{rule_id} not in rule_registry"
        assert len(registered) >= len(expected)
