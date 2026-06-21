# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""HTTP client for the deps.dev API (v3alpha).

Provides version metadata, version detail, and dependency lookups for
packages across pypi, npm, maven, nuget, and go ecosystems.  All methods
degrade gracefully — returning ``None`` on any network, HTTP, or parse
failure — so callers never need to handle exceptions from this module.
"""

from __future__ import annotations

import atexit
import gzip
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.deps.dev/v3alpha"


_SENTINEL = object()
_shared_cache: dict[str, dict | None] = {}
_cache_dirty = False
_cache_file: Path | None = None


def _load_file_cache(path: Path) -> None:
    """Load a gzipped JSON cache file into ``_shared_cache``."""
    global _cache_file
    _cache_file = path
    if not path.exists():
        logger.info("deps.dev file cache: %s does not exist yet, starting empty", path)
        return
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            data = json.load(f)
        _shared_cache.update(data)
        logger.info("deps.dev file cache: loaded %d entries from %s", len(data), path)
    except (json.JSONDecodeError, gzip.BadGzipFile, OSError) as exc:
        logger.warning("deps.dev file cache: failed to load %s: %s", path, exc)


def _save_file_cache() -> None:
    """Write ``_shared_cache`` to the configured cache file (atexit handler)."""
    if _cache_file is None or not _cache_dirty:
        return
    try:
        _cache_file.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(_cache_file, "wt", encoding="utf-8") as f:
            json.dump(_shared_cache, f, ensure_ascii=False, sort_keys=True)
        logger.info(
            "deps.dev file cache: saved %d entries to %s",
            len(_shared_cache),
            _cache_file,
        )
    except OSError as exc:
        logger.warning("deps.dev file cache: failed to save %s: %s", _cache_file, exc)


_cache_path_env = os.environ.get("NFR_DEPS_DEV_CACHE")
if _cache_path_env:
    _load_file_cache(Path(_cache_path_env))
    atexit.register(_save_file_cache)


class DepsDevClient:
    """Thin HTTP client for deps.dev public API lookups."""

    def __init__(self, timeout: int = 10) -> None:
        self._timeout = timeout

    def _get(self, path: str) -> dict | None:
        global _cache_dirty

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
            _cache_dirty = True
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
        _cache_dirty = True
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
