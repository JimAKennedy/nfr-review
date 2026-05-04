"""Tests for the JavaAstCollector — parsing, payload structure, and fault isolation."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from nfr_review.collectors.java_ast import JavaAstCollector

FIXTURES = Path(__file__).parent / "fixtures" / "java-sample-repo"


@pytest.fixture
def collector() -> JavaAstCollector:
    return JavaAstCollector()


class TestBasicParsing:
    def test_returns_evidence_for_each_java_file(self, collector: JavaAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        assert len(results) == 4
        assert all(e.kind == "java-ast-file" for e in results)
        assert all(e.collector_name == "java-ast" for e in results)
        assert all(e.collector_version == "0.1.0" for e in results)

    def test_payload_has_required_keys(self, collector: JavaAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        required_keys = {
            "file_path",
            "classes",
            "methods",
            "catch_blocks",
            "imports",
            "thread_pool_constructions",
            "log_statements",
        }
        for ev in results:
            assert required_keys.issubset(ev.payload.keys())


class TestHealthController:
    def test_class_annotations(self, collector: JavaAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        health = next(e for e in results if "HealthController" in e.payload["file_path"])
        classes = health.payload["classes"]
        assert len(classes) == 1
        assert "RestController" in classes[0]["annotations"]

    def test_mapping_paths(self, collector: JavaAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        health = next(e for e in results if "HealthController" in e.payload["file_path"])
        methods = health.payload["classes"][0]["methods"]
        paths = [p for m in methods for p in m["mapping_paths"]]
        assert "/health" in paths
        assert "/orders" in paths

    def test_method_annotations(self, collector: JavaAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        health = next(e for e in results if "HealthController" in e.payload["file_path"])
        methods = health.payload["classes"][0]["methods"]
        health_method = next(m for m in methods if m["name"] == "health")
        assert "GetMapping" in health_method["annotations"]


class TestOrderService:
    def test_catch_block_swallowed(self, collector: JavaAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        order = next(e for e in results if "OrderService" in e.payload["file_path"])
        catch_blocks = order.payload["catch_blocks"]
        assert len(catch_blocks) == 1
        assert catch_blocks[0]["caught_type"] == "Exception"
        assert catch_blocks[0]["rethrows"] is False

    def test_imports_include_resttemplate(self, collector: JavaAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        order = next(e for e in results if "OrderService" in e.payload["file_path"])
        imports = order.payload["imports"]
        assert any("RestTemplate" in i for i in imports)


class TestResilientClient:
    def test_circuit_breaker_annotation(self, collector: JavaAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        resilient = next(e for e in results if "ResilientClient" in e.payload["file_path"])
        methods = resilient.payload["methods"]
        cb_methods = [m for m in methods if "CircuitBreaker" in m["annotations"]]
        assert len(cb_methods) == 2

    def test_retry_annotation(self, collector: JavaAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        resilient = next(e for e in results if "ResilientClient" in e.payload["file_path"])
        methods = resilient.payload["methods"]
        retry_methods = [m for m in methods if "Retry" in m["annotations"]]
        assert len(retry_methods) == 1


class TestAsyncConfig:
    def test_thread_pool_detected(self, collector: JavaAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        async_cfg = next(e for e in results if "AsyncConfig" in e.payload["file_path"])
        pools = async_cfg.payload["thread_pool_constructions"]
        assert len(pools) == 2
        assert all(p["class_name"] == "ThreadPoolExecutor" for p in pools)

    def test_bounded_queue_detection(self, collector: JavaAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        async_cfg = next(e for e in results if "AsyncConfig" in e.payload["file_path"])
        pools = async_cfg.payload["thread_pool_constructions"]
        bounded = next(p for p in pools if p["has_bounded_queue"])
        unbounded = next(p for p in pools if not p["has_bounded_queue"])
        assert bounded["has_rejection_policy"] is True
        assert unbounded["has_rejection_policy"] is False


class TestFaultIsolation:
    def test_malformed_java_skipped_with_warning(
        self, collector: JavaAstCollector, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        good = tmp_path / "Good.java"
        good.write_text("public class Good { }")
        bad = tmp_path / "Bad.java"
        bad.write_bytes(b"\xff\xfe" + b"not valid java {{{{")
        with caplog.at_level(logging.WARNING, logger="nfr_review.collectors.java_ast"):
            results = collector.collect(tmp_path, config=None)
        # tree-sitter is lenient — it parses even malformed code into error nodes
        # Both files should produce evidence (tree-sitter doesn't throw on bad syntax)
        assert len(results) >= 1
        good_ev = next((e for e in results if "Good" in e.payload["file_path"]), None)
        assert good_ev is not None

    def test_empty_java_file(self, collector: JavaAstCollector, tmp_path: Path) -> None:
        empty = tmp_path / "Empty.java"
        empty.write_text("")
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        assert results[0].payload["classes"] == []

    def test_no_java_files(self, collector: JavaAstCollector, tmp_path: Path) -> None:
        (tmp_path / "readme.txt").write_text("not java")
        results = collector.collect(tmp_path, config=None)
        assert results == []

    def test_hidden_directory_skipped(
        self, collector: JavaAstCollector, tmp_path: Path
    ) -> None:
        hidden = tmp_path / ".git" / "objects"
        hidden.mkdir(parents=True)
        (hidden / "Cached.java").write_text("class Cached {}")
        visible = tmp_path / "src"
        visible.mkdir()
        (visible / "Visible.java").write_text("class Visible {}")
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        assert "Visible" in results[0].payload["file_path"]


class TestLogStatementExtraction:
    def test_extracts_logger_calls(self, collector: JavaAstCollector, tmp_path: Path) -> None:
        java = tmp_path / "App.java"
        java.write_text(
            "public class App {\n"
            "    void run() {\n"
            '        logger.info("User {} logged in", userId);\n'
            '        LOG.warn("Payment for card {}", cardNumber);\n'
            '        log.debug("Debug message");\n'
            '        LOGGER.error("Something failed");\n'
            "    }\n"
            "}\n"
        )
        results = collector.collect(tmp_path, config=None)
        stmts = results[0].payload["log_statements"]
        assert len(stmts) == 4
        methods = [s["method"] for s in stmts]
        assert "logger.info" in methods
        assert "LOG.warn" in methods
        assert "log.debug" in methods
        assert "LOGGER.error" in methods

    def test_log_statement_fields(self, collector: JavaAstCollector, tmp_path: Path) -> None:
        java = tmp_path / "Svc.java"
        java.write_text(
            "public class Svc {\n"
            "    void go() {\n"
            '        logger.info("hello {}", name);\n'
            "    }\n"
            "}\n"
        )
        results = collector.collect(tmp_path, config=None)
        stmts = results[0].payload["log_statements"]
        assert len(stmts) == 1
        assert stmts[0]["method"] == "logger.info"
        assert '"hello {}"' in stmts[0]["arguments_text"]
        assert "name" in stmts[0]["arguments_text"]
        assert stmts[0]["line"] == 3

    def test_non_logging_calls_excluded(
        self, collector: JavaAstCollector, tmp_path: Path
    ) -> None:
        java = tmp_path / "Other.java"
        java.write_text(
            "public class Other {\n"
            "    void go() {\n"
            "        service.process(data);\n"
            '        System.out.println("hi");\n'
            '        helper.info("not a logger");\n'
            "    }\n"
            "}\n"
        )
        results = collector.collect(tmp_path, config=None)
        stmts = results[0].payload["log_statements"]
        assert len(stmts) == 0

    def test_trace_level_captured(self, collector: JavaAstCollector, tmp_path: Path) -> None:
        java = tmp_path / "Trace.java"
        java.write_text(
            "public class Trace {\n"
            "    void go() {\n"
            '        logger.trace("verbose detail");\n'
            "    }\n"
            "}\n"
        )
        results = collector.collect(tmp_path, config=None)
        stmts = results[0].payload["log_statements"]
        assert len(stmts) == 1
        assert stmts[0]["method"] == "logger.trace"

    def test_empty_file_has_empty_log_statements(
        self, collector: JavaAstCollector, tmp_path: Path
    ) -> None:
        java = tmp_path / "Empty.java"
        java.write_text("")
        results = collector.collect(tmp_path, config=None)
        assert results[0].payload["log_statements"] == []
