"""HTTP client for the deps.dev API (v3alpha).

Provides version metadata, version detail, and dependency lookups for
packages across pypi, npm, maven, nuget, and go ecosystems.  All methods
degrade gracefully — returning ``None`` on any network, HTTP, or parse
failure — so callers never need to handle exceptions from this module.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.deps.dev/v3alpha"


_SENTINEL = object()
_shared_cache: dict[str, dict | None] = {}


class DepsDevClient:
    """Thin HTTP client for deps.dev public API lookups."""

    def __init__(self, timeout: int = 10) -> None:
        self._timeout = timeout

    def _get(self, path: str) -> dict | None:
        cached = _shared_cache.get(path, _SENTINEL)
        if cached is not _SENTINEL:
            logger.debug("deps.dev API: cache hit for %s", path)
            return cached  # type: ignore[return-value]

        url = f"{_BASE_URL}/{path}"
        logger.info("deps.dev API: GET %s", path)
        t0 = time.monotonic()
        try:
            req = urllib.request.Request(url)  # noqa: S310  # nosec B310
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # noqa: S310  # nosec B310
                body = resp.read()
            elapsed = time.monotonic() - t0
            logger.info("deps.dev API: %s responded in %.2fs", path, elapsed)
            result = json.loads(body)
            _shared_cache[path] = result
            return result
        except urllib.error.HTTPError as exc:
            elapsed = time.monotonic() - t0
            logger.info("deps.dev API: %s HTTP %d in %.2fs", path, exc.code, elapsed)
        except urllib.error.URLError as exc:
            elapsed = time.monotonic() - t0
            logger.info("deps.dev API: %s failed (%s) in %.2fs", path, exc.reason, elapsed)
        except json.JSONDecodeError as exc:
            logger.debug(
                "deps.dev lookup failed for %s: malformed JSON — %s",
                path,
                exc,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("deps.dev lookup failed for %s: %s", path, exc)
        _shared_cache[path] = None
        return None

    def get_package_versions(self, ecosystem: str, package_name: str) -> dict | None:
        encoded = urllib.parse.quote(package_name, safe="")
        return self._get(f"systems/{ecosystem}/packages/{encoded}")

    def prefetch_package_versions(
        self, ecosystem: str, package_names: list[str], *, max_workers: int = 8
    ) -> None:
        """Warm the cache for multiple packages concurrently."""
        uncached = [
            name
            for name in package_names
            if f"systems/{ecosystem}/packages/{urllib.parse.quote(name, safe='')}"
            not in _shared_cache
        ]
        if not uncached:
            return

        logger.info(
            "Prefetching %d/%d %s packages (%d workers)",
            len(uncached),
            len(package_names),
            ecosystem,
            min(max_workers, len(uncached)),
        )
        t0 = time.monotonic()

        def _fetch(name: str) -> None:
            self.get_package_versions(ecosystem, name)

        with ThreadPoolExecutor(max_workers=min(max_workers, len(uncached))) as pool:
            futures = [pool.submit(_fetch, name) for name in uncached]
            for fut in as_completed(futures):
                fut.result()

        elapsed = time.monotonic() - t0
        logger.info(
            "Prefetch complete: %d packages in %.2fs (%.1fx speedup)",
            len(uncached),
            elapsed,
            (len(uncached) * 0.3) / max(elapsed, 0.01),
        )

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


def pick_latest_version(versions: list[dict]) -> dict | None:
    """Select the latest version from a deps.dev versions list.

    Prefers the version marked ``isDefault`` by the registry, falls back
    to the most recently published version, and finally to the last element.
    """
    if not versions:
        return None

    for v in versions:
        if v.get("isDefault"):
            return v

    with_date = [(v, v.get("publishedAt", "")) for v in versions]
    if any(d for _, d in with_date):
        return max(with_date, key=lambda pair: pair[1])[0]

    return versions[-1]


__all__ = ["DepsDevClient", "pick_latest_version"]
