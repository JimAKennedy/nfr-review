# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""A scancode install that is present but broken must not crash nfr-review.

plugincode 32.0.0 (a scancode-toolkit dependency) raises ValueError at
import under pluggy 1.7. The collector only caught ImportError, so that
escaped and took down every command that loads the hygiene collectors.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap


def test_broken_scancode_import_disables_collector_instead_of_crashing() -> None:
    script = textwrap.dedent(
        """
        import importlib.abc
        import logging
        import sys

        class _Broken(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path=None, target=None):
                if name == "scancode.api" or name.startswith("scancode.api."):
                    raise ValueError("did not find any 'plugincode.location_provider' hooks")
                return None

        sys.meta_path.insert(0, _Broken())
        logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

        from nfr_review.hygiene.collectors import license_scan

        print("AVAILABLE", license_scan._SCANCODE_AVAILABLE)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
    assert "AVAILABLE False" in result.stdout
    assert "scancode-toolkit is installed but failed to import" in result.stderr
