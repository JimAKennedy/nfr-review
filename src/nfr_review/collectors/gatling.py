# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Gatling collector — scans for Gatling simulation results and emits
per-simulation Evidence with parsed performance metrics.

Evidence payload contract (kind="gatling-result"):
    simulation_dir: str — path relative to repo_path
    total_requests: int
    ok_requests: int
    ko_requests: int
    error_rate: float — percentage of failed requests (0.0-100.0)
    mean_response_time_ms: float
    p50_response_time_ms: float
    p75_response_time_ms: float
    p95_response_time_ms: float
    p99_response_time_ms: float
    min_response_time_ms: float
    max_response_time_ms: float
    requests_per_second: float

Evidence payload contract (kind="gatling-summary"):
    simulation_count: int
    simulations: list[str] — relative paths to simulation dirs
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from nfr_review.models import Evidence
from nfr_review.registry import collector_registry

logger = logging.getLogger("nfr_review.collectors.gatling")

_HIDDEN_DIRS = frozenset({".git", ".svn", ".hg", ".idea", ".vscode", "node_modules"})

# Patterns for locating Gatling stats.json files
_STATS_PATTERNS = [
    "target/gatling/*/js/stats.json",
    "results/*/js/stats.json",
    "target/gatling/*/stats.json",
    "results/*/stats.json",
    "build/reports/gatling/*/js/stats.json",
]


def _is_hidden(rel: Path) -> bool:
    """Return True if any path component is a hidden dir or in _HIDDEN_DIRS."""
    return any(part.startswith(".") or part in _HIDDEN_DIRS for part in rel.parts)


def _extract_metrics(data: dict[str, Any]) -> dict[str, Any] | None:
    """Extract performance metrics from a Gatling stats.json structure."""
    stats = data.get("stats")
    if not stats:
        return None

    num_requests = stats.get("numberOfRequests", {})
    total = num_requests.get("total", 0)
    ok = num_requests.get("ok", 0)
    ko = num_requests.get("ko", 0)

    error_rate = (ko / total * 100.0) if total > 0 else 0.0

    mean_rt = stats.get("meanResponseTime", {})
    min_rt = stats.get("minResponseTime", {})
    max_rt = stats.get("maxResponseTime", {})
    p50 = stats.get("percentiles1", {})
    p75 = stats.get("percentiles2", {})
    p95 = stats.get("percentiles3", {})
    p99 = stats.get("percentiles4", {})
    rps = stats.get("meanNumberOfRequestsPerSecond", {})

    return {
        "total_requests": total,
        "ok_requests": ok,
        "ko_requests": ko,
        "error_rate": round(error_rate, 2),
        "mean_response_time_ms": mean_rt.get("total", 0),
        "p50_response_time_ms": p50.get("total", 0),
        "p75_response_time_ms": p75.get("total", 0),
        "p95_response_time_ms": p95.get("total", 0),
        "p99_response_time_ms": p99.get("total", 0),
        "min_response_time_ms": min_rt.get("total", 0),
        "max_response_time_ms": max_rt.get("total", 0),
        "requests_per_second": rps.get("total", 0.0),
    }


class GatlingCollector:
    name = "gatling"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        evidence: list[Evidence] = []
        seen: set[Path] = set()
        simulation_dirs: list[str] = []

        for pattern in _STATS_PATTERNS:
            for stats_file in sorted(repo_path.glob(pattern)):
                if not stats_file.is_file():
                    continue

                resolved = stats_file.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)

                rel = stats_file.relative_to(repo_path)
                if _is_hidden(rel):
                    continue

                try:
                    raw = stats_file.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError) as exc:
                    logger.debug("Cannot read %s: %s", rel, exc)
                    continue

                try:
                    data = json.loads(raw)
                except json.JSONDecodeError as exc:
                    logger.debug("JSON parse error in %s: %s", rel, exc)
                    continue

                metrics = _extract_metrics(data)
                if metrics is None:
                    logger.debug("No stats section in %s", rel)
                    continue

                # Use the simulation directory as the locator
                sim_dir = str(rel.parent)
                simulation_dirs.append(sim_dir)

                payload = {"simulation_dir": sim_dir, **metrics}

                evidence.append(
                    Evidence(
                        collector_name=self.name,
                        collector_version=self.version,
                        locator=str(rel),
                        kind="gatling-result",
                        payload=payload,
                    )
                )

        # Emit a summary evidence if any simulations were found
        if simulation_dirs:
            evidence.append(
                Evidence(
                    collector_name=self.name,
                    collector_version=self.version,
                    locator="gatling-summary",
                    kind="gatling-summary",
                    payload={
                        "simulation_count": len(simulation_dirs),
                        "simulations": simulation_dirs,
                    },
                )
            )

        return evidence


def _register() -> None:
    if "gatling" not in collector_registry:
        collector_registry.register("gatling", GatlingCollector())


_register()

__all__ = ["GatlingCollector"]
