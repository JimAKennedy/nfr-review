# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Istio collector — parses Istio CRDs from YAML files and emits structured
evidence about service mesh configuration.

Evidence payload contract (kind="istio-analysis"):
    file_path: str — path relative to repo_path
    resources: list[dict] — each with:
        kind: str — Istio CRD kind (PeerAuthentication, DestinationRule, etc.)
        api_version: str — full apiVersion string
        name: str — metadata.name
        namespace: str | None — metadata.namespace
        spec: dict — full spec section
        line: int — approximate line number (1-based, from document index)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML, YAMLError

from nfr_review.collectors.payloads.istio import IstioAnalysisPayload, IstioResource
from nfr_review.models import Evidence
from nfr_review.path_filter import compile_exclude_patterns, should_exclude_path
from nfr_review.registry import collector_registry

logger = logging.getLogger("nfr_review.collectors.istio")

_HIDDEN_DIRS = frozenset({".git", ".svn", ".hg", ".idea", ".vscode", "node_modules"})

_ISTIO_API_PATTERN = re.compile(r"^[a-z0-9-]+\.istio\.io/")


class IstioCollector:
    name = "istio"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        evidence: list[Evidence] = []
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
                content = yaml_file.read_bytes()
            except OSError as exc:
                logger.debug("Cannot read %s: %s", rel, exc)
                continue

            try:
                docs = list(yaml.load_all(content))
            except YAMLError as exc:
                logger.debug("YAML parse error in %s: %s", rel, exc)
                continue

            resources: list[IstioResource] = []
            for doc_index, doc in enumerate(docs):
                if not isinstance(doc, dict):
                    continue
                api_version = doc.get("apiVersion", "")
                if not isinstance(api_version, str):
                    continue
                if not _ISTIO_API_PATTERN.match(api_version):
                    continue
                kind = doc.get("kind")
                if not kind:
                    continue
                metadata = doc.get("metadata", {}) or {}
                resources.append(
                    IstioResource(
                        kind=kind,
                        api_version=api_version,
                        name=metadata.get("name", ""),
                        namespace=metadata.get("namespace") or None,
                        spec=doc.get("spec", {}),
                        line=doc_index + 1,
                    )
                )

            if resources:
                evidence.append(
                    Evidence(
                        collector_name=self.name,
                        collector_version=self.version,
                        locator=str(rel),
                        kind="istio-analysis",
                        payload=IstioAnalysisPayload(
                            file_path=str(rel),
                            resources=resources,
                        ),
                    )
                )

        return evidence


def _register() -> None:
    if "istio" not in collector_registry:
        collector_registry.register("istio", IstioCollector())


_register()

__all__ = ["IstioCollector"]
