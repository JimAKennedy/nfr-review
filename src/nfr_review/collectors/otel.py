# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""OTel collector — parses OpenTelemetry Collector configuration YAML files
and detects SDK-level instrumentation config across project files.

Evidence payload contract (kind="otel-analysis"):
    file_path: str — path relative to repo_path
    receivers: list[str] — receiver names configured
    processors: list[str] — processor names configured
    exporters: list[str] — exporter names configured
    pipelines: dict — service.pipelines section (signal type -> component lists)

Evidence payload contract (kind="otel-sdk-config"):
    agent_attached: bool — OTel agent found in test/runtime config
    exporter_type: str|None — detected exporter type (otlp, file, etc.)
    propagators: list[str] — configured propagation formats
    resource_attributes: dict[str,str] — detected resource attributes
    source_file: str — file where config was found
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML, YAMLError

from nfr_review.collectors.payloads.otel import OtelAnalysisPayload, OtelSdkConfigPayload
from nfr_review.models import Evidence
from nfr_review.path_filter import compile_exclude_patterns, should_exclude_path
from nfr_review.registry import collector_registry

logger = logging.getLogger("nfr_review.collectors.otel")

_HIDDEN_DIRS = frozenset({".git", ".svn", ".hg", ".idea", ".vscode", "node_modules"})

_OTEL_COLLECTOR_NAME_PARTS = ("otel", "otelcol", "opentelemetry")

_REQUIRED_TOP_LEVEL_KEYS = {"receivers", "exporters", "service"}

_JAVAAGENT_RE = re.compile(r"-javaagent:\S*opentelemetry-javaagent", re.IGNORECASE)
_OTEL_ENV_RE = re.compile(r"OTEL_\w+")
_PROPAGATOR_RE = re.compile(r"OTEL_PROPAGATORS\s*[=:]\s*(\S+)")
_EXPORTER_RE = re.compile(r"OTEL_TRACES_EXPORTER\s*[=:]\s*(\S+)")
_SERVICE_NAME_RE = re.compile(r"OTEL_SERVICE_NAME\s*[=:]\s*(\S+)")
_RESOURCE_ATTRS_RE = re.compile(r"OTEL_RESOURCE_ATTRIBUTES\s*[=:]\s*(\S+)")


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


def _parse_resource_attrs(raw: str) -> dict[str, str]:
    """Parse OTEL_RESOURCE_ATTRIBUTES value like 'service.name=foo,service.version=1.0'."""
    attrs: dict[str, str] = {}
    for pair in raw.split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            attrs[k.strip()] = v.strip()
    return attrs


def _extract_env_vars(text: str) -> dict[str, str]:
    """Extract OTEL_* env var assignments from text content."""
    env_vars: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        for pattern in [
            re.compile(r"(\bOTEL_\w+)\s*[=:]\s*[\"']?([^\"'\s#]+)"),
        ]:
            for m in pattern.finditer(stripped):
                env_vars[m.group(1)] = m.group(2)
    return env_vars


def _sdk_config_from_env_vars(
    env_vars: dict[str, str], source_file: str, agent_attached: bool = False
) -> OtelSdkConfigPayload | None:
    """Build an OtelSdkConfigPayload from extracted env vars if any OTel config found."""
    if not env_vars and not agent_attached:
        return None

    propagators: list[str] = []
    if "OTEL_PROPAGATORS" in env_vars:
        propagators = [p.strip() for p in env_vars["OTEL_PROPAGATORS"].split(",")]

    exporter_type: str | None = env_vars.get("OTEL_TRACES_EXPORTER")

    resource_attrs: dict[str, str] = {}
    if "OTEL_SERVICE_NAME" in env_vars:
        resource_attrs["service.name"] = env_vars["OTEL_SERVICE_NAME"]
    if "OTEL_RESOURCE_ATTRIBUTES" in env_vars:
        resource_attrs.update(_parse_resource_attrs(env_vars["OTEL_RESOURCE_ATTRIBUTES"]))

    return OtelSdkConfigPayload(
        agent_attached=agent_attached or bool(env_vars),
        exporter_type=exporter_type,
        propagators=propagators,
        resource_attributes=resource_attrs,
        source_file=source_file,
    )


def _scan_yaml_for_sdk_config(
    doc: dict[str, Any], rel: str, text: str
) -> OtelSdkConfigPayload | None:
    """Scan a YAML doc (docker-compose, CI workflow) for OTel SDK config."""
    env_vars = _extract_env_vars(text)
    otel_vars = {k: v for k, v in env_vars.items() if k.startswith("OTEL_")}
    agent_attached = bool(_JAVAAGENT_RE.search(text))
    return _sdk_config_from_env_vars(otel_vars, rel, agent_attached)


def _scan_spring_yaml_for_otel(doc: dict[str, Any], rel: str) -> OtelSdkConfigPayload | None:
    """Scan Spring Boot application YAML for OTel properties."""
    if not isinstance(doc, dict):
        return None

    otel_section = _deep_get(doc, "otel") or _deep_get(doc, "opentelemetry")

    management = _deep_get(doc, "management") or {}
    tracing = _deep_get(management, "tracing") or {}

    propagators: list[str] = []
    propagation = _deep_get(tracing, "propagation") or {}
    if isinstance(propagation, dict):
        prop_type = propagation.get("type")
        if prop_type:
            propagators = (
                [p.strip() for p in prop_type.split(",")]
                if isinstance(prop_type, str)
                else list(prop_type)
            )

    resource_attrs: dict[str, str] = {}
    spring_app_name = _deep_get(doc, "spring", "application", "name")
    if spring_app_name:
        resource_attrs["service.name"] = str(spring_app_name)

    exporter_type: str | None = None
    otlp_conf = _deep_get(tracing, "export") or _deep_get(otel_section or {}, "exporter")
    if otlp_conf:
        exporter_type = "otlp"

    has_anything = bool(
        otel_section or tracing or propagators or resource_attrs or exporter_type
    )
    if not has_anything:
        return None

    return OtelSdkConfigPayload(
        agent_attached=False,
        exporter_type=exporter_type,
        propagators=propagators,
        resource_attributes=resource_attrs,
        source_file=rel,
    )


def _deep_get(d: dict[str, Any] | Any, *keys: str) -> Any:
    """Safely traverse nested dicts."""
    current = d
    for k in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(k)
    return current


def _scan_pom_xml(path: Path, rel: str) -> OtelSdkConfigPayload | None:
    """Scan Maven pom.xml for OTel agent JVM args in surefire/failsafe plugins."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    agent_attached = bool(_JAVAAGENT_RE.search(text))
    otel_vars = {k: v for k, v in _extract_env_vars(text).items() if k.startswith("OTEL_")}

    if not agent_attached and not otel_vars:
        return None

    return _sdk_config_from_env_vars(otel_vars, rel, agent_attached)


def _scan_dockerfile(path: Path, rel: str) -> OtelSdkConfigPayload | None:
    """Scan Dockerfile for OTel env vars and agent attachment."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    env_vars: dict[str, str] = {}
    agent_attached = False

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.upper().startswith("ENV "):
            line_vars = _extract_env_vars(stripped[4:])
            env_vars.update({k: v for k, v in line_vars.items() if k.startswith("OTEL_")})
        if _JAVAAGENT_RE.search(stripped):
            agent_attached = True

    return _sdk_config_from_env_vars(env_vars, rel, agent_attached)


def _is_hidden(rel: Path) -> bool:
    return any(
        part.startswith(".") or part in _HIDDEN_DIRS
        for part in rel.parts
        if part != "." and not part.startswith(".github")
    )


class OTelCollector:
    name = "otel"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        evidence: list[Evidence] = []
        exclude_test = getattr(config, "exclude_test_paths", True)
        exclude_pats = compile_exclude_patterns(getattr(config, "exclude_paths", []))
        yaml = YAML(typ="safe")

        sdk_configs_seen: set[str] = set()

        for yaml_file in sorted(repo_path.rglob("*.y*ml")):
            rel = yaml_file.relative_to(repo_path)
            if _is_hidden(rel):
                continue
            if yaml_file.suffix not in (".yaml", ".yml"):
                continue
            if should_exclude_path(
                str(rel), exclude_test_paths=exclude_test, exclude_patterns=exclude_pats
            ):
                continue

            try:
                content = yaml_file.read_bytes()
                text = content.decode("utf-8", errors="replace")
            except OSError as exc:
                logger.debug("Cannot read %s: %s", rel, exc)
                continue

            try:
                doc = yaml.load(content)
            except YAMLError as exc:
                logger.debug("YAML parse error in %s: %s", rel, exc)
                continue

            if not isinstance(doc, dict):
                continue

            if _is_otel_collector_config(yaml_file, doc):
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
                        payload=OtelAnalysisPayload(
                            file_path=str(rel),
                            receivers=receivers,
                            processors=processors,
                            exporters=exporters,
                            pipelines=pipelines,
                        ),
                    )
                )

            rel_str = str(rel)
            name_lower = yaml_file.name.lower()

            sdk_payload: OtelSdkConfigPayload | None = None
            if name_lower.startswith("application"):
                sdk_payload = _scan_spring_yaml_for_otel(doc, rel_str)
            elif name_lower.startswith("docker-compose") or "OTEL_" in text:
                sdk_payload = _scan_yaml_for_sdk_config(doc, rel_str, text)

            if sdk_payload and rel_str not in sdk_configs_seen:
                sdk_configs_seen.add(rel_str)
                evidence.append(
                    Evidence(
                        collector_name=self.name,
                        collector_version=self.version,
                        locator=rel_str,
                        kind="otel-sdk-config",
                        payload=sdk_payload,
                    )
                )

        for pom_file in sorted(repo_path.rglob("pom.xml")):
            rel = pom_file.relative_to(repo_path)
            if _is_hidden(rel):
                continue
            rel_str = str(rel)
            if rel_str in sdk_configs_seen:
                continue
            sdk_payload = _scan_pom_xml(pom_file, rel_str)
            if sdk_payload:
                sdk_configs_seen.add(rel_str)
                evidence.append(
                    Evidence(
                        collector_name=self.name,
                        collector_version=self.version,
                        locator=rel_str,
                        kind="otel-sdk-config",
                        payload=sdk_payload,
                    )
                )

        for dockerfile in sorted(repo_path.rglob("Dockerfile*")):
            rel = dockerfile.relative_to(repo_path)
            if _is_hidden(rel):
                continue
            if not dockerfile.is_file():
                continue
            rel_str = str(rel)
            if rel_str in sdk_configs_seen:
                continue
            sdk_payload = _scan_dockerfile(dockerfile, rel_str)
            if sdk_payload:
                sdk_configs_seen.add(rel_str)
                evidence.append(
                    Evidence(
                        collector_name=self.name,
                        collector_version=self.version,
                        locator=rel_str,
                        kind="otel-sdk-config",
                        payload=sdk_payload,
                    )
                )

        return evidence


def _register() -> None:
    if "otel" not in collector_registry:
        collector_registry.register("otel", OTelCollector())


_register()

__all__ = ["OTelCollector"]
