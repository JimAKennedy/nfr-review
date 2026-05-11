"""Helm collector — renders charts via ``helm template`` and emits per-chart
Evidence with structured payload for downstream NFR rules.

Evidence payload contract (kind="helm-analysis"):
    chart_path: str — path relative to repo_path
    chart_name: str | None
    chart_version: str | None
    app_version: str | None
    description: str | None
    values: dict — parsed values.yaml
    rendered_manifests: list[dict] — K8s resources from ``helm template``
    template_files: list[str] — template file paths relative to chart dir
    helm_available: bool — whether the helm binary was found on PATH
"""

from __future__ import annotations

import logging
import shutil
import subprocess  # nosec B404
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from nfr_review.models import Evidence
from nfr_review.registry import collector_registry

logger = logging.getLogger("nfr_review.collectors.helm")

_HIDDEN_DIRS = frozenset({".git", ".svn", ".hg", ".idea", ".vscode", "node_modules"})
_HELM_TEMPLATE_TIMEOUT = 30


def _is_hidden(path: Path, repo_root: Path) -> bool:
    rel = path.relative_to(repo_root)
    return any(part.startswith(".") or part in _HIDDEN_DIRS for part in rel.parts)


def _find_charts(repo_path: Path) -> list[Path]:
    try:
        candidates = sorted(repo_path.rglob("Chart.yaml"))
    except OSError:
        return []
    return [p.parent for p in candidates if p.is_file() and not _is_hidden(p, repo_path)]


def _parse_yaml_file(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        yaml = YAML()
        yaml.preserve_quotes = True
        data = yaml.load(path)
        return dict(data) if data else {}
    except Exception as exc:  # noqa: BLE001
        logger.debug("Cannot parse %s: %s", path, exc)
        return None


def _parse_yaml_docs(text: str) -> list[dict[str, Any]]:
    yaml = YAML()
    yaml.preserve_quotes = True
    docs: list[dict[str, Any]] = []
    try:
        for doc in yaml.load_all(text):
            if isinstance(doc, dict):
                docs.append(dict(doc))
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed to parse rendered YAML: %s", exc)
    return docs


def _list_templates(chart_dir: Path) -> list[str]:
    templates_dir = chart_dir / "templates"
    if not templates_dir.is_dir():
        return []
    try:
        return sorted(
            str(f.relative_to(chart_dir)) for f in templates_dir.rglob("*") if f.is_file()
        )
    except OSError:
        return []


class HelmCollector:
    name = "helm"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        chart_dirs = _find_charts(repo_path)
        if not chart_dirs:
            return []

        helm_bin = shutil.which("helm")
        if helm_bin is None:
            logger.warning("helm binary not found on PATH — skipping Helm evidence collection")

        evidence: list[Evidence] = []
        for chart_dir in chart_dirs:
            rel_chart = str(chart_dir.relative_to(repo_path))

            chart_meta = _parse_yaml_file(chart_dir / "Chart.yaml")
            if chart_meta is None:
                logger.debug("Cannot read Chart.yaml in %s, skipping chart", rel_chart)
                continue

            values = _parse_yaml_file(chart_dir / "values.yaml") or {}
            template_files = _list_templates(chart_dir)

            rendered_manifests: list[dict[str, Any]] = []
            if helm_bin is not None:
                rendered_manifests = self._render_chart(chart_dir, rel_chart)

            evidence.append(
                Evidence(
                    collector_name=self.name,
                    collector_version=self.version,
                    locator=rel_chart,
                    kind="helm-analysis",
                    payload={
                        "chart_path": rel_chart,
                        "chart_name": chart_meta.get("name"),
                        "chart_version": chart_meta.get("version"),
                        "app_version": chart_meta.get("appVersion"),
                        "description": chart_meta.get("description"),
                        "maintainers": chart_meta.get("maintainers"),
                        "values": values,
                        "rendered_manifests": rendered_manifests,
                        "template_files": template_files,
                        "helm_available": helm_bin is not None,
                    },
                )
            )
        return evidence

    def _render_chart(self, chart_dir: Path, rel_chart: str) -> list[dict[str, Any]]:
        try:
            result = subprocess.run(  # noqa: S603  # nosec B603 B607
                ["helm", "template", "."],
                cwd=chart_dir,
                capture_output=True,
                text=True,
                timeout=_HELM_TEMPLATE_TIMEOUT,
            )
            result.check_returncode()
            return _parse_yaml_docs(result.stdout)
        except subprocess.CalledProcessError as exc:
            logger.debug(
                "helm template failed for %s (exit %d): %s",
                rel_chart,
                exc.returncode,
                exc.stderr[:200] if exc.stderr else "",
            )
        except subprocess.TimeoutExpired:
            logger.debug(
                "helm template timed out for %s after %ds",
                rel_chart,
                _HELM_TEMPLATE_TIMEOUT,
            )
        except FileNotFoundError:
            logger.debug("helm binary disappeared while rendering %s", rel_chart)
        return []


def _register() -> None:
    if "helm" not in collector_registry:
        collector_registry.register("helm", HelmCollector())


_register()

__all__ = ["HelmCollector"]
