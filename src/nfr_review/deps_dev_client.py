"""HTTP client for the deps.dev API (v3alpha).

Provides version metadata, version detail, and dependency lookups for
packages across pypi, npm, maven, nuget, and go ecosystems.  All methods
degrade gracefully — returning ``None`` on any network, HTTP, or parse
failure — so callers never need to handle exceptions from this module.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.deps.dev/v3alpha"


class DepsDevClient:
    """Thin HTTP client for deps.dev public API lookups."""

    def __init__(self, timeout: int = 10) -> None:
        self._timeout = timeout

    def _get(self, path: str) -> dict | None:
        url = f"{_BASE_URL}/{path}"
        try:
            req = urllib.request.Request(url)  # noqa: S310  # nosec B310
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # noqa: S310  # nosec B310
                body = resp.read()
            return json.loads(body)
        except urllib.error.HTTPError as exc:
            logger.debug("deps.dev lookup failed for %s: HTTP %d", path, exc.code)
        except urllib.error.URLError as exc:
            logger.debug("deps.dev lookup failed for %s: %s", path, exc.reason)
        except json.JSONDecodeError as exc:
            logger.debug(
                "deps.dev lookup failed for %s: malformed JSON — %s",
                path,
                exc,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("deps.dev lookup failed for %s: %s", path, exc)
        return None

    def get_package_versions(self, ecosystem: str, package_name: str) -> dict | None:
        encoded = urllib.parse.quote(package_name, safe="")
        return self._get(f"systems/{ecosystem}/packages/{encoded}")

    def get_version_info(self, ecosystem: str, package_name: str, version: str) -> dict | None:
        encoded_pkg = urllib.parse.quote(package_name, safe="")
        encoded_ver = urllib.parse.quote(version, safe="")
        return self._get(f"systems/{ecosystem}/packages/{encoded_pkg}/versions/{encoded_ver}")

    def get_dependencies(
        self, ecosystem: str, package_name: str, version: str
    ) -> list[dict] | None:
        encoded_pkg = urllib.parse.quote(package_name, safe="")
        encoded_ver = urllib.parse.quote(version, safe="")
        data = self._get(
            f"systems/{ecosystem}/packages/{encoded_pkg}/versions/{encoded_ver}:dependencies"
        )
        if data is None:
            return None
        return data.get("nodes", [])

    def get_dependency_graph(
        self, ecosystem: str, package_name: str, version: str
    ) -> dict | None:
        """Return the full dependency graph (nodes + edges) for a version."""
        encoded_pkg = urllib.parse.quote(package_name, safe="")
        encoded_ver = urllib.parse.quote(version, safe="")
        return self._get(
            f"systems/{ecosystem}/packages/{encoded_pkg}/versions/{encoded_ver}:dependencies"
        )


__all__ = ["DepsDevClient"]
