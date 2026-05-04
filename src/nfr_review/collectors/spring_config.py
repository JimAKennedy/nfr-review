"""Spring config collector — parses application*.yaml and *.properties files
and emits per-file Evidence with structured payload for downstream NFR rules.

Evidence payload contract (kind="spring-config-file"):
    file_path: str — path relative to repo_path
    profile: str | None — extracted from filename (e.g. "prod" from application-prod.yaml)
    management: dict — management.* keys (nested)
    logging: dict — logging.* keys (nested)
    server: dict — server.* keys (nested)
    spring_security: dict — spring.security.* keys (nested)
    actuator: dict — management.endpoints.web.exposure include/exclude
    raw_keys: list[str] — all top-level keys
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from nfr_review.models import Evidence
from nfr_review.registry import collector_registry

logger = logging.getLogger("nfr_review.collectors.spring_config")

_HIDDEN_DIRS = frozenset({".git", ".svn", ".hg", ".idea", ".vscode", "node_modules"})

_SPRING_CONFIG_PATTERN = re.compile(
    r"^(application|bootstrap)(-[\w]+)?\.(ya?ml|properties)$"
)

_PROFILE_PATTERN = re.compile(r"^application-(.+)\.(ya?ml|properties)$")


def _is_hidden(rel: Path) -> bool:
    """Return True if any path component is a hidden dir or in _HIDDEN_DIRS."""
    return any(part.startswith(".") or part in _HIDDEN_DIRS for part in rel.parts)


def _deep_get(data: dict[str, Any], *keys: str) -> Any:
    """Walk nested dicts by key path, returning None if any key is missing."""
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _parse_properties(text: str) -> dict[str, Any]:
    """Parse a Java .properties file into a nested dict.

    Supports simple key=value and key: value lines.
    Lines starting with # or ! are comments. Blank lines are skipped.
    """
    result: dict[str, Any] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("!"):
            continue
        # Split on first = or :
        for sep in ("=", ":"):
            idx = stripped.find(sep)
            if idx >= 0:
                key = stripped[:idx].strip()
                value = stripped[idx + 1 :].strip()
                _set_nested(result, key.split("."), value)
                break
    return result


def _set_nested(d: dict[str, Any], keys: list[str], value: Any) -> None:
    """Set a value in a nested dict using a list of keys (dot-split path)."""
    for key in keys[:-1]:
        if key not in d or not isinstance(d[key], dict):
            d[key] = {}
        d = d[key]
    d[keys[-1]] = value


def _extract_payload(
    data: dict[str, Any], rel_path: str, profile: str | None,
) -> dict[str, Any]:
    """Build the evidence payload from parsed config data."""
    management = data.get("management", {}) or {}
    logging_section = data.get("logging", {}) or {}
    server = data.get("server", {}) or {}

    # Extract spring.security subtree
    spring = data.get("spring", {}) or {}
    spring_security = _deep_get(spring, "security") or {}

    # Extract actuator exposure settings
    actuator: dict[str, Any] = {}
    exposure = _deep_get(management, "endpoints", "web", "exposure")
    if isinstance(exposure, dict):
        if "include" in exposure:
            actuator["include"] = exposure["include"]
        if "exclude" in exposure:
            actuator["exclude"] = exposure["exclude"]

    return {
        "file_path": rel_path,
        "profile": profile,
        "management": management,
        "logging": logging_section,
        "server": server,
        "spring_security": spring_security,
        "actuator": actuator,
        "raw_keys": sorted(data.keys()) if isinstance(data, dict) else [],
    }


class SpringConfigCollector:
    name = "spring-config"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        evidence: list[Evidence] = []
        yaml = YAML(typ="safe")

        seen: set[Path] = set()

        for config_file in sorted(repo_path.rglob("*")):
            if not config_file.is_file():
                continue
            if not _SPRING_CONFIG_PATTERN.match(config_file.name):
                continue

            resolved = config_file.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)

            rel = config_file.relative_to(repo_path)
            if _is_hidden(rel):
                continue

            # Extract profile from filename
            profile_match = _PROFILE_PATTERN.match(config_file.name)
            profile = profile_match.group(1) if profile_match else None

            try:
                raw = config_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                logger.warning("Cannot read %s: %s", rel, exc)
                continue

            try:
                if config_file.suffix == ".properties":
                    data = _parse_properties(raw)
                else:
                    data = yaml.load(raw)
                    if data is None:
                        data = {}
                    if not isinstance(data, dict):
                        logger.warning(
                            "Skipping %s: YAML root is not a mapping (got %s)",
                            rel,
                            type(data).__name__,
                        )
                        continue
            except Exception as exc:  # noqa: BLE001
                logger.warning("Parse error in %s: %s", rel, exc)
                continue

            payload = _extract_payload(data, str(rel), profile)

            evidence.append(
                Evidence(
                    collector_name=self.name,
                    collector_version=self.version,
                    locator=str(rel),
                    kind="spring-config-file",
                    payload=payload,
                )
            )

        return evidence


def _register() -> None:
    if "spring-config" not in collector_registry:
        collector_registry.register("spring-config", SpringConfigCollector())


_register()

__all__ = ["SpringConfigCollector"]
