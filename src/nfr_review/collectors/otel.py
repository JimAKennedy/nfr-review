"""OTel Collector config collector — parses OpenTelemetry Collector configuration
YAML files and emits structured evidence about pipeline topology.

Evidence payload contract (kind="otel-analysis"):
    file_path: str — path relative to repo_path
    receivers: list[str] — receiver names configured
    processors: list[str] — processor names configured
    exporters: list[str] — exporter names configured
    pipelines: dict — service.pipelines section (signal type -> component lists)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML, YAMLError

from nfr_review.models import Evidence
from nfr_review.registry import collector_registry

logger = logging.getLogger("nfr_review.collectors.otel")

_HIDDEN_DIRS = frozenset({".git", ".svn", ".hg", ".idea", ".vscode", "node_modules"})

_OTEL_COLLECTOR_NAME_PARTS = ("otel", "otelcol", "opentelemetry")

_REQUIRED_TOP_LEVEL_KEYS = {"receivers", "exporters", "service"}


def _is_otel_collector_config(path: Path, doc: dict[str, Any]) -> bool:
    name_lower = path.name.lower()
    if any(part in name_lower for part in _OTEL_COLLECTOR_NAME_PARTS):
        if _REQUIRED_TOP_LEVEL_KEYS.issubset(doc.keys()):
            return True

    if _REQUIRED_TOP_LEVEL_KEYS.issubset(doc.keys()):
        service = doc.get("service")
        if isinstance(service, dict) and "pipelines" in service:
            return True

    return False


class OTelCollector:
    name = "otel"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        evidence: list[Evidence] = []
        yaml = YAML(typ="safe")

        for yaml_file in sorted(repo_path.rglob("*.y*ml")):
            rel = yaml_file.relative_to(repo_path)
            if any(part.startswith(".") or part in _HIDDEN_DIRS for part in rel.parts):
                continue
            if yaml_file.suffix not in (".yaml", ".yml"):
                continue

            try:
                content = yaml_file.read_bytes()
            except OSError as exc:
                logger.warning("Cannot read %s: %s", rel, exc)
                continue

            try:
                doc = yaml.load(content)
            except YAMLError as exc:
                logger.warning("YAML parse error in %s: %s", rel, exc)
                continue

            if not isinstance(doc, dict):
                continue

            if not _is_otel_collector_config(yaml_file, doc):
                continue

            receivers = (
                sorted(doc.get("receivers", {}).keys())
                if isinstance(doc.get("receivers"), dict)
                else []
            )
            processors = (
                sorted(doc.get("processors", {}).keys())
                if isinstance(doc.get("processors"), dict)
                else []
            )
            exporters = (
                sorted(doc.get("exporters", {}).keys())
                if isinstance(doc.get("exporters"), dict)
                else []
            )

            service = doc.get("service", {})
            pipelines = service.get("pipelines", {}) if isinstance(service, dict) else {}

            evidence.append(
                Evidence(
                    collector_name=self.name,
                    collector_version=self.version,
                    locator=str(rel),
                    kind="otel-analysis",
                    payload={
                        "file_path": str(rel),
                        "receivers": receivers,
                        "processors": processors,
                        "exporters": exporters,
                        "pipelines": pipelines,
                    },
                )
            )

        return evidence


def _register() -> None:
    if "otel" not in collector_registry:
        collector_registry.register("otel", OTelCollector())


_register()

__all__ = ["OTelCollector"]
