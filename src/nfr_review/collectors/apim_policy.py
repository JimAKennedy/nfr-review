# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""APIM Policy collector -- parses Azure API Management policy XML files
and emits per-file Evidence with structured payload for downstream NFR rules.

Evidence payload contract (kind="apim-policy"):
    file_path: str -- path relative to repo_path
    has_rate_limit: bool -- any <rate-limit> or <rate-limit-by-key> in <inbound>
    has_auth_policy: bool -- any <validate-jwt> or <authentication-managed-identity>
    backend_urls: list[str] -- base-url values from <set-backend-service>
    uses_named_values: bool -- any {{...}} patterns in backend URLs
    inbound_policies: list[str] -- tag names of inbound children
    outbound_policies: list[str] -- tag names of outbound children
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET  # nosec B405
from pathlib import Path
from typing import Any

from nfr_review.collectors.payloads.apim import ApimPolicyPayload
from nfr_review.models import Evidence
from nfr_review.registry import collector_registry

logger = logging.getLogger("nfr_review.collectors.apim_policy")

_HIDDEN_DIRS = frozenset({".git", ".svn", ".hg", ".idea", ".vscode", "node_modules"})
_POLICY_DIRS = ("policies", "apim", "api-management")
_RATE_LIMIT_TAGS = frozenset({"rate-limit", "rate-limit-by-key"})
_AUTH_TAGS = frozenset({"validate-jwt", "authentication-managed-identity"})
_NAMED_VALUE_RE = re.compile(r"\{\{.+?\}\}")


def _is_hidden(rel: Path) -> bool:
    return any(part.startswith(".") or part in _HIDDEN_DIRS for part in rel.parts)


def _discover_xml_files(repo_path: Path) -> list[Path]:
    """Discover candidate APIM policy XML files."""
    seen: set[Path] = set()
    files: list[Path] = []

    # Check well-known directories
    for dirname in _POLICY_DIRS:
        candidate = repo_path / dirname
        if candidate.is_dir():
            for xml_file in sorted(candidate.rglob("*.xml")):
                rel = xml_file.relative_to(repo_path)
                if not _is_hidden(rel) and xml_file not in seen:
                    seen.add(xml_file)
                    files.append(xml_file)

    # Also find *policy*.xml anywhere in the repo
    for xml_file in sorted(repo_path.rglob("*policy*.xml")):
        rel = xml_file.relative_to(repo_path)
        if not _is_hidden(rel) and xml_file not in seen:
            seen.add(xml_file)
            files.append(xml_file)

    return files


def _parse_policy(xml_path: Path, repo_path: Path) -> ApimPolicyPayload | None:
    """Parse a single APIM policy XML file and return the payload dict.

    Returns None if the file is not a valid APIM policy (no <policies> root).
    """
    tree = ET.parse(xml_path)  # noqa: S314  # nosec B314
    root = tree.getroot()

    if root.tag != "policies":
        return None

    inbound = root.find("inbound")
    backend = root.find("backend")
    outbound = root.find("outbound")

    # Inbound policy tags
    inbound_policies: list[str] = []
    has_rate_limit = False
    has_auth_policy = False
    if inbound is not None:
        for child in inbound:
            inbound_policies.append(child.tag)
            if child.tag in _RATE_LIMIT_TAGS:
                has_rate_limit = True
            if child.tag in _AUTH_TAGS:
                has_auth_policy = True

    # Outbound policy tags
    outbound_policies: list[str] = []
    if outbound is not None:
        for child in outbound:
            outbound_policies.append(child.tag)

    # Backend URLs
    backend_urls: list[str] = []
    if backend is not None:
        for svc in backend.iter("set-backend-service"):
            url = svc.get("base-url", "")
            if url:
                backend_urls.append(url)

    # Named values check
    uses_named_values = any(_NAMED_VALUE_RE.search(url) for url in backend_urls)

    rel_path = xml_path.relative_to(repo_path)
    return ApimPolicyPayload(
        file_path=str(rel_path),
        has_rate_limit=has_rate_limit,
        has_auth_policy=has_auth_policy,
        backend_urls=backend_urls,
        uses_named_values=uses_named_values,
        inbound_policies=inbound_policies,
        outbound_policies=outbound_policies,
    )


class ApimPolicyCollector:
    """Collect evidence from Azure API Management policy XML files."""

    name = "apim-policy"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        evidence: list[Evidence] = []
        xml_files = _discover_xml_files(repo_path)

        for xml_file in xml_files:
            rel = xml_file.relative_to(repo_path)
            try:
                payload = _parse_policy(xml_file, repo_path)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Error parsing %s: %s", rel, exc)
                continue

            if payload is None:
                logger.debug(
                    "Skipping %s: not an APIM policy file (no <policies> root)",
                    rel,
                )
                continue

            evidence.append(
                Evidence(
                    collector_name=self.name,
                    collector_version=self.version,
                    locator=str(rel),
                    kind="apim-policy",
                    payload=payload,
                )
            )
        return evidence


def _register() -> None:
    if "apim-policy" not in collector_registry:
        collector_registry.register("apim-policy", ApimPolicyCollector())


_register()

__all__ = ["ApimPolicyCollector"]
