# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""ADR derivation collector — uses the Claude LLM to infer what Architecture
Decision Records should exist based on repo content.

This is a Band 2 collector that analyses tech stack signals (config files,
existing ADRs, README) and asks the LLM to propose candidate ADRs.

Evidence payload contract (kind="adr-derived"):
    title: str — proposed ADR title
    rationale: str — why this ADR should exist
    category: str — one of framework/infrastructure/data/integration/security/
                     observability/testing/deployment
    confidence: float — 0.0–1.0, strength of evidence
    evidence_refs: list[str] — files/patterns supporting the inference

Evidence payload contract (kind="adr-derive-summary"):
    total_derived: int — number of candidate ADRs proposed
    categories: dict[str, int] — category → count
    avg_confidence: float — mean confidence across all derived ADRs

Evidence payload contract (kind="adr-derive-skip"):
    reason: str — why derivation was skipped
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from nfr_review.collectors.payloads.adr_derive import (
    AdrDerivedPayload,
    AdrDeriveSkipPayload,
    AdrDeriveSummaryPayload,
)
from nfr_review.llm_client import create_llm_client, serialize_evidence_bundle
from nfr_review.models import Evidence
from nfr_review.registry import collector_registry

logger = logging.getLogger(__name__)

_ADR_DIRS = ("docs/adr", "doc/adr", "adr", "docs/decisions")

_CONFIG_FILES = (
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "package.json",
    "requirements.txt",
    "pyproject.toml",
    "setup.py",
    "go.mod",
    "Cargo.toml",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "Makefile",
    "CMakeLists.txt",
)

_CONFIG_GLOBS = (
    (".github/workflows", "*.yml"),
    (".github/workflows", "*.yaml"),
    ("terraform", "*.tf"),
    ("helm", "Chart.yaml"),
)

_PROMPT = """\
You are an architecture analyst. Given the repository context below, infer \
Architecture Decision Records (ADRs) that *should* exist for this project.

Focus on **architecture decisions** — technology choices, framework adoption, \
infrastructure patterns, data storage strategies, integration approaches, \
security postures, observability strategies — NOT implementation details.

Return a JSON array of objects. Each object must have exactly these keys:
- "title": string — concise ADR title (e.g. "Use PostgreSQL for persistence")
- "rationale": string — 1-2 sentence explanation of why this decision matters
- "category": string — one of: framework, infrastructure, data, integration, \
security, observability, testing, deployment
- "confidence": number — 0.0 to 1.0 indicating strength of evidence \
(direct config file evidence = 0.8+, indirect inference = 0.4-0.7)
- "evidence_refs": array of strings — file paths or patterns that support \
the inference

Return between 5 and 15 ADRs. Output ONLY the JSON array, no other text.
"""


def _extract_json(text: str) -> list[dict] | None:
    """Try to extract a JSON array from *text*, tolerating markdown fences.

    Returns ``None`` if no valid JSON array can be found.
    """
    # 1. Try direct parse
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except (json.JSONDecodeError, ValueError):
        pass

    # 2. Try ```json ... ``` code block
    fence_match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    if fence_match:
        try:
            result = json.loads(fence_match.group(1))
            if isinstance(result, list):
                return result
        except (json.JSONDecodeError, ValueError):
            pass

    # 3. Try to find bare [ ... ]
    bracket_match = re.search(r"\[.*\]", text, re.DOTALL)
    if bracket_match:
        try:
            result = json.loads(bracket_match.group(0))
            if isinstance(result, list):
                return result
        except (json.JSONDecodeError, ValueError):
            pass

    return None


def _gather_context(repo_path: Path) -> list[dict[str, Any]]:
    """Gather lightweight context from the repo for the LLM prompt."""
    context: list[dict[str, Any]] = []

    # Check top-level config files
    for name in _CONFIG_FILES:
        cfg = repo_path / name
        if cfg.is_file():
            try:
                head = cfg.read_text(encoding="utf-8", errors="replace")[:500]
            except OSError:
                head = "(unreadable)"
            context.append({"type": "config_file", "path": name, "head": head})

    # Check glob-based config locations
    for directory, pattern in _CONFIG_GLOBS:
        parent = repo_path / directory
        if parent.is_dir():
            for match in sorted(parent.glob(pattern))[:5]:
                rel = str(match.relative_to(repo_path))
                try:
                    head = match.read_text(encoding="utf-8", errors="replace")[:300]
                except OSError:
                    head = "(unreadable)"
                context.append({"type": "config_file", "path": rel, "head": head})

    # Read existing ADR files
    for adr_dir in _ADR_DIRS:
        candidate = repo_path / adr_dir
        if candidate.is_dir():
            for md_file in sorted(candidate.glob("*.md"))[:20]:
                rel = str(md_file.relative_to(repo_path))
                try:
                    head = md_file.read_text(encoding="utf-8", errors="replace")[:500]
                except OSError:
                    head = "(unreadable)"
                context.append({"type": "existing_adr", "path": rel, "head": head})

    # Read README
    readme = repo_path / "README.md"
    if readme.is_file():
        try:
            lines = readme.read_text(encoding="utf-8", errors="replace").splitlines()[:200]
            context.append({"type": "readme", "path": "README.md", "head": "\n".join(lines)})
        except OSError:
            pass

    return context


class AdrDeriveCollector:
    """Use the Claude LLM to infer candidate ADRs from repo content."""

    name = "adr-derive"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        client = create_llm_client()

        if not client.available:
            return [
                Evidence(
                    collector_name=self.name,
                    collector_version=self.version,
                    locator="adr-derive",
                    kind="adr-derive-skip",
                    payload=AdrDeriveSkipPayload(
                        reason="ANTHROPIC_API_KEY is not set; LLM analysis unavailable"
                    ),
                )
            ]

        context = _gather_context(repo_path)
        bundle = serialize_evidence_bundle(context)

        try:
            raw_response = client.analyze(
                prompt=_PROMPT,
                evidence_bundle=bundle,
                max_tokens=2048,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM analysis failed: %s", exc)
            return [
                Evidence(
                    collector_name=self.name,
                    collector_version=self.version,
                    locator="adr-derive",
                    kind="adr-derive-skip",
                    payload=AdrDeriveSkipPayload(reason=f"LLM analysis failed: {exc}"),
                )
            ]

        parsed = _extract_json(raw_response)
        if parsed is None:
            logger.warning("Failed to parse LLM response as JSON")
            return [
                Evidence(
                    collector_name=self.name,
                    collector_version=self.version,
                    locator="adr-derive",
                    kind="adr-derive-skip",
                    payload=AdrDeriveSkipPayload(
                        reason="Failed to parse LLM response as JSON"
                    ),
                )
            ]

        evidence: list[Evidence] = []
        categories: dict[str, int] = {}
        total_confidence = 0.0

        for item in parsed[:15]:
            title = item.get("title", "Untitled")
            rationale = item.get("rationale", "")
            category = item.get("category", "framework")
            confidence = float(item.get("confidence", 0.5))
            evidence_refs = item.get("evidence_refs", [])

            categories[category] = categories.get(category, 0) + 1
            total_confidence += confidence

            evidence.append(
                Evidence(
                    collector_name=self.name,
                    collector_version=self.version,
                    locator=f"adr-derived:{title}",
                    kind="adr-derived",
                    payload=AdrDerivedPayload(
                        title=title,
                        rationale=rationale,
                        category=category,
                        confidence=confidence,
                        evidence_refs=evidence_refs,
                    ),
                )
            )

        if evidence:
            avg_confidence = total_confidence / len(evidence)
            evidence.append(
                Evidence(
                    collector_name=self.name,
                    collector_version=self.version,
                    locator="adr-derive-summary",
                    kind="adr-derive-summary",
                    payload=AdrDeriveSummaryPayload(
                        total_derived=len([e for e in evidence if e.kind == "adr-derived"]),
                        categories=categories,
                        avg_confidence=round(avg_confidence, 3),
                    ),
                )
            )

        return evidence


def _register() -> None:
    if "adr-derive" not in collector_registry:
        collector_registry.register("adr-derive", AdrDeriveCollector())


_register()

__all__ = ["AdrDeriveCollector"]
