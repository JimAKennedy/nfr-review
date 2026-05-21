# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Telemetry config collector — deep extraction of OTel collector pipeline topology,
resource attributes, exporter targets, SDK instrumentation patterns, and synthetic
test configurations.

Complements the lightweight ``otel`` collector with the richer evidence needed by
PATCH-TELEM rules (golden-signal coverage, mandatory labels, synthetic transactions).

Evidence payload contracts
--------------------------

kind="telemetry-pipeline" (per OTel collector config file):
    file_path: str
    receivers: list[str]
    processors: list[str]
    exporters: list[str]
    pipelines: dict[str, dict] — signal -> {receivers, processors, exporters}
    signal_types: list[str] — e.g. ["metrics", "traces", "logs"]
    exporter_targets: list[dict] — [{name, type, endpoint}]
    resource_attributes: dict — merged resource attrs from processors/resource block
    extensions: list[str]

kind="telemetry-sdk-init" (per source file with OTel SDK bootstrapping):
    file_path: str
    language: str
    sdk_packages: list[str]
    instrumentation_type: str — "auto" | "manual" | "unknown"
    configured_signals: list[str]

kind="telemetry-synthetic-config" (per synthetic test definition):
    file_path: str
    tool: str
    test_type: str
    targets: list[str]
    frequency: str | None

kind="telemetry-config-summary":
    collector_configs_found: int
    sdk_instrumentations_found: int
    synthetic_configs_found: int
    signal_coverage: dict[str, bool]
    files_parsed: int
    files_failed: int
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML, YAMLError

from nfr_review.models import Evidence
from nfr_review.path_filter import compile_exclude_patterns, should_exclude_path
from nfr_review.registry import collector_registry

logger = logging.getLogger("nfr_review.collectors.telemetry_config")

_HIDDEN_DIRS = frozenset({".git", ".svn", ".hg", ".idea", ".vscode", "node_modules"})

_OTEL_NAME_PARTS = ("otel", "otelcol", "opentelemetry", "collector-config")

_REQUIRED_OTEL_KEYS = {"receivers", "exporters", "service"}

_EXPORTER_ENDPOINT_KEYS = ("endpoint", "url", "site", "host")

_SDK_PATTERNS: dict[str, dict[str, Any]] = {
    ".py": {
        "language": "python",
        "auto_markers": [
            re.compile(r"opentelemetry[\._]instrumentation"),
            re.compile(r"from\s+opentelemetry\.sdk\._?logs\b"),
        ],
        "import_pattern": re.compile(r"(?:from|import)\s+(opentelemetry[\w.]*)"),
        "signal_patterns": {
            "traces": re.compile(r"TracerProvider|trace\.get_tracer"),
            "metrics": re.compile(r"MeterProvider|metrics\.get_meter"),
            "logs": re.compile(r"LoggerProvider|_logs\.get_logger"),
        },
    },
    ".java": {
        "language": "java",
        "auto_markers": [
            re.compile(r"opentelemetry-javaagent"),
            re.compile(r"io\.opentelemetry\.javaagent"),
        ],
        "import_pattern": re.compile(r"import\s+(io\.opentelemetry[\w.]*)"),
        "signal_patterns": {
            "traces": re.compile(r"TracerProvider|GlobalOpenTelemetry\.getTracer"),
            "metrics": re.compile(r"MeterProvider|GlobalOpenTelemetry\.getMeter"),
            "logs": re.compile(r"LoggerProvider"),
        },
    },
    ".go": {
        "language": "go",
        "auto_markers": [],
        "import_pattern": re.compile(r'"(go\.opentelemetry\.io/otel[^"]*)"'),
        "signal_patterns": {
            "traces": re.compile(r"trace\.NewTracerProvider|otel\.SetTracerProvider"),
            "metrics": re.compile(r"metric\.NewMeterProvider|otel\.SetMeterProvider"),
            "logs": re.compile(r"log\.NewLoggerProvider"),
        },
    },
    ".js": {
        "language": "javascript",
        "auto_markers": [
            re.compile(r"@opentelemetry/auto-instrumentations"),
            re.compile(r"@opentelemetry/sdk-node"),
        ],
        "import_pattern": re.compile(
            r"""(?:require\s*\(\s*['"]|from\s+['"])(@opentelemetry/[\w./-]*)"""
        ),
        "signal_patterns": {
            "traces": re.compile(r"NodeTracerProvider|BasicTracerProvider"),
            "metrics": re.compile(r"MeterProvider|PeriodicExportingMetricReader"),
            "logs": re.compile(r"LoggerProvider"),
        },
    },
    ".ts": {
        "language": "typescript",
        "auto_markers": [
            re.compile(r"@opentelemetry/auto-instrumentations"),
            re.compile(r"@opentelemetry/sdk-node"),
        ],
        "import_pattern": re.compile(
            r"""(?:require\s*\(\s*['"]|from\s+['"])(@opentelemetry/[\w./-]*)"""
        ),
        "signal_patterns": {
            "traces": re.compile(r"NodeTracerProvider|BasicTracerProvider"),
            "metrics": re.compile(r"MeterProvider|PeriodicExportingMetricReader"),
            "logs": re.compile(r"LoggerProvider"),
        },
    },
    ".cs": {
        "language": "csharp",
        "auto_markers": [
            re.compile(r"OpenTelemetry\.AutoInstrumentation"),
        ],
        "import_pattern": re.compile(r"using\s+(OpenTelemetry[\w.]*)"),
        "signal_patterns": {
            "traces": re.compile(r"AddOpenTelemetry|WithTracing|TracerProvider"),
            "metrics": re.compile(r"WithMetrics|MeterProvider"),
            "logs": re.compile(r"WithLogging|OpenTelemetryLoggerProvider"),
        },
    },
}

_SOURCE_EXTENSIONS = frozenset(_SDK_PATTERNS.keys())

_SYNTHETIC_TOOL_MARKERS: list[dict[str, Any]] = [
    {
        "tool": "grafana-synthetic-monitoring",
        "keys": {"checks"},
        "api_version_prefix": "synthetic-monitoring",
    },
    {
        "tool": "datadog-synthetics",
        "keys": {"type", "config"},
        "type_field_values": {"api", "browser", "grpc"},
    },
    {
        "tool": "checkly",
        "keys": {"checks", "project"},
        "filename_hint": "checkly",
    },
]


def _is_otel_collector_config(path: Path, doc: dict[str, Any]) -> bool:
    name_lower = path.name.lower()
    if any(part in name_lower for part in _OTEL_NAME_PARTS):
        if _REQUIRED_OTEL_KEYS.issubset(doc.keys()):
            return True

    if _REQUIRED_OTEL_KEYS.issubset(doc.keys()):
        service = doc.get("service")
        if isinstance(service, dict) and "pipelines" in service:
            return True

    return False


def _extract_exporter_targets(exporters: dict[str, Any]) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for name, cfg in exporters.items():
        if not isinstance(cfg, dict):
            cfg = {}
        base_type = name.split("/")[0]
        endpoint = None
        for key in _EXPORTER_ENDPOINT_KEYS:
            val = cfg.get(key)
            if val:
                endpoint = str(val)
                break
        targets.append(
            {
                "name": name,
                "type": base_type,
                "endpoint": endpoint,
            }
        )
    return targets


def _extract_resource_attributes(doc: dict[str, Any]) -> dict[str, Any]:
    attrs: dict[str, Any] = {}

    processors = doc.get("processors")
    if isinstance(processors, dict):
        for pname, pcfg in processors.items():
            if not isinstance(pcfg, dict):
                continue
            base = pname.split("/")[0]
            if base in ("resource", "resourcedetection", "attributes"):
                action_list = pcfg.get("attributes") or []
                if isinstance(action_list, list):
                    for action in action_list:
                        if isinstance(action, dict) and action.get("action") == "upsert":
                            k = action.get("key")
                            v = action.get("value")
                            if k:
                                attrs[k] = v

    service = doc.get("service")
    if isinstance(service, dict):
        telemetry = service.get("telemetry")
        if isinstance(telemetry, dict):
            resource = telemetry.get("resource")
            if isinstance(resource, dict):
                attrs.update(resource)

    return attrs


def _extract_pipelines(doc: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    service = doc.get("service")
    if not isinstance(service, dict):
        return {}
    raw = service.get("pipelines")
    if not isinstance(raw, dict):
        return {}

    pipelines: dict[str, dict[str, list[str]]] = {}
    for key, cfg in raw.items():
        if not isinstance(cfg, dict):
            continue
        pipelines[key] = {
            "receivers": sorted(cfg.get("receivers") or []),
            "processors": sorted(cfg.get("processors") or []),
            "exporters": sorted(cfg.get("exporters") or []),
        }
    return pipelines


def _signal_types_from_pipelines(
    pipelines: dict[str, dict[str, list[str]]],
) -> list[str]:
    signals: set[str] = set()
    for key in pipelines:
        base = key.split("/")[0]
        if base in ("metrics", "traces", "logs"):
            signals.add(base)
    return sorted(signals)


def _detect_synthetic_config(path: Path, doc: dict[str, Any]) -> dict[str, Any] | None:
    name_lower = path.name.lower()
    doc_keys = set(doc.keys())

    if isinstance(doc.get("checks"), list):
        if "checkly" in name_lower or ("project" in doc_keys and "checks" in doc_keys):
            tests = doc["checks"]
            targets = []
            for t in tests:
                if isinstance(t, dict):
                    url = t.get("url") or t.get("request", {}).get("url")
                    if url:
                        targets.append(str(url))
            return {
                "tool": "checkly",
                "test_type": "api",
                "targets": targets,
                "frequency": str(t.get("frequency"))
                if tests and isinstance(tests[0], dict) and "frequency" in tests[0]
                else None,
            }

        targets = []
        for c in doc["checks"]:
            if isinstance(c, dict):
                url = c.get("target") or c.get("url") or c.get("endpoint")
                if url:
                    targets.append(str(url))
        freq = None
        if isinstance(doc["checks"], list) and doc["checks"]:
            first = doc["checks"][0]
            if isinstance(first, dict):
                freq = str(first.get("frequency") or first.get("interval") or "")
                if not freq:
                    freq = None
        return {
            "tool": "grafana-synthetic-monitoring",
            "test_type": "http",
            "targets": targets,
            "frequency": freq,
        }

    if doc.get("type") in ("api", "browser", "grpc", "multistep") and "config" in doc_keys:
        cfg = doc.get("config", {})
        request = cfg.get("request", {}) if isinstance(cfg, dict) else {}
        url = request.get("url") or ""
        return {
            "tool": "datadog-synthetics",
            "test_type": str(doc["type"]),
            "targets": [str(url)] if url else [],
            "frequency": str(cfg.get("tick_every"))
            if isinstance(cfg, dict) and cfg.get("tick_every")
            else None,
        }

    if "synthetics" in name_lower and isinstance(doc.get("tests"), list):
        targets = []
        for t in doc["tests"]:
            if isinstance(t, dict):
                url = t.get("url") or t.get("target")
                if url:
                    targets.append(str(url))
        return {
            "tool": "generic-synthetic",
            "test_type": "http",
            "targets": targets,
            "frequency": None,
        }

    return None


def _scan_sdk_file(path: Path, content: str, repo_path: Path) -> dict[str, Any] | None:
    suffix = path.suffix
    spec = _SDK_PATTERNS.get(suffix)
    if spec is None:
        return None

    import_matches = spec["import_pattern"].findall(content)
    if not import_matches:
        return None

    is_auto = any(p.search(content) for p in spec["auto_markers"])

    signals: list[str] = []
    for signal, pat in spec["signal_patterns"].items():
        if pat.search(content):
            signals.append(signal)

    instr_type = "auto" if is_auto else ("manual" if signals else "unknown")

    rel = path.relative_to(repo_path)
    return {
        "file_path": str(rel),
        "language": spec["language"],
        "sdk_packages": sorted(set(import_matches)),
        "instrumentation_type": instr_type,
        "configured_signals": sorted(signals),
    }


class TelemetryConfigCollector:
    name = "telemetry-config"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        evidence: list[Evidence] = []
        files_parsed = 0
        files_failed = 0
        collector_configs_found = 0
        sdk_instrumentations_found = 0
        synthetic_configs_found = 0
        signal_coverage: dict[str, bool] = {
            "metrics": False,
            "traces": False,
            "logs": False,
        }
        exclude_test = getattr(config, "exclude_test_paths", True)
        exclude_pats = compile_exclude_patterns(getattr(config, "exclude_paths", []))

        yaml = YAML(typ="safe")

        for yaml_file in sorted(repo_path.rglob("*.y*ml")):
            rel = yaml_file.relative_to(repo_path)
            if any(part.startswith(".") or part in _HIDDEN_DIRS for part in rel.parts):
                continue
            if yaml_file.suffix not in (".yaml", ".yml"):
                continue
            if should_exclude_path(
                str(rel), exclude_test_paths=exclude_test, exclude_patterns=exclude_pats
            ):
                continue

            try:
                raw = yaml_file.read_bytes()
            except OSError as exc:
                logger.debug("Cannot read %s: %s", rel, exc)
                files_failed += 1
                continue

            try:
                doc = yaml.load(raw)
            except YAMLError as exc:
                logger.debug("YAML parse error in %s: %s", rel, exc)
                files_failed += 1
                continue

            if not isinstance(doc, dict):
                continue

            if _is_otel_collector_config(yaml_file, doc):
                files_parsed += 1
                collector_configs_found += 1

                receivers_raw = doc.get("receivers", {})
                receivers = (
                    sorted(receivers_raw.keys()) if isinstance(receivers_raw, dict) else []
                )
                processors_raw = doc.get("processors", {})
                processors = (
                    sorted(processors_raw.keys()) if isinstance(processors_raw, dict) else []
                )
                exporters_raw = doc.get("exporters", {})
                exporters = (
                    sorted(exporters_raw.keys()) if isinstance(exporters_raw, dict) else []
                )

                exporter_targets = _extract_exporter_targets(
                    exporters_raw if isinstance(exporters_raw, dict) else {}
                )
                resource_attributes = _extract_resource_attributes(doc)
                pipelines = _extract_pipelines(doc)
                signal_types = _signal_types_from_pipelines(pipelines)

                for sig in signal_types:
                    if sig in signal_coverage:
                        signal_coverage[sig] = True

                extensions_raw = doc.get("extensions", {})
                extensions = (
                    sorted(extensions_raw.keys()) if isinstance(extensions_raw, dict) else []
                )

                evidence.append(
                    Evidence(
                        collector_name=self.name,
                        collector_version=self.version,
                        locator=str(rel),
                        kind="telemetry-pipeline",
                        payload={
                            "file_path": str(rel),
                            "receivers": receivers,
                            "processors": processors,
                            "exporters": exporters,
                            "pipelines": pipelines,
                            "signal_types": signal_types,
                            "exporter_targets": exporter_targets,
                            "resource_attributes": resource_attributes,
                            "extensions": extensions,
                        },
                    )
                )
                continue

            synth = _detect_synthetic_config(yaml_file, doc)
            if synth is not None:
                files_parsed += 1
                synthetic_configs_found += 1
                evidence.append(
                    Evidence(
                        collector_name=self.name,
                        collector_version=self.version,
                        locator=str(rel),
                        kind="telemetry-synthetic-config",
                        payload={
                            "file_path": str(rel),
                            **synth,
                        },
                    )
                )

        for src_file in sorted(repo_path.rglob("*")):
            if not src_file.is_file():
                continue
            if src_file.suffix not in _SOURCE_EXTENSIONS:
                continue
            rel = src_file.relative_to(repo_path)
            if any(part.startswith(".") or part in _HIDDEN_DIRS for part in rel.parts):
                continue
            if should_exclude_path(
                str(rel), exclude_test_paths=exclude_test, exclude_patterns=exclude_pats
            ):
                continue

            try:
                content = src_file.read_text(errors="replace")
            except OSError:
                continue

            sdk_info = _scan_sdk_file(src_file, content, repo_path)
            if sdk_info is not None:
                sdk_instrumentations_found += 1
                for sig in sdk_info["configured_signals"]:
                    if sig in signal_coverage:
                        signal_coverage[sig] = True
                evidence.append(
                    Evidence(
                        collector_name=self.name,
                        collector_version=self.version,
                        locator=str(rel),
                        kind="telemetry-sdk-init",
                        payload=sdk_info,
                    )
                )

        evidence.append(
            Evidence(
                collector_name=self.name,
                collector_version=self.version,
                locator=".",
                kind="telemetry-config-summary",
                payload={
                    "collector_configs_found": collector_configs_found,
                    "sdk_instrumentations_found": sdk_instrumentations_found,
                    "synthetic_configs_found": synthetic_configs_found,
                    "signal_coverage": signal_coverage,
                    "files_parsed": files_parsed,
                    "files_failed": files_failed,
                },
            )
        )

        return evidence


def _register() -> None:
    if "telemetry-config" not in collector_registry:
        collector_registry.register("telemetry-config", TelemetryConfigCollector())


_register()

__all__ = ["TelemetryConfigCollector"]
