from __future__ import annotations

import tomllib
from pathlib import Path

from nfr_review import __version__

_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_version_is_set() -> None:
    meta = tomllib.loads(_PYPROJECT.read_text())
    expected = meta["project"]["version"]
    assert __version__ == expected
