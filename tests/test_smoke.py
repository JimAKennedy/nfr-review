from __future__ import annotations

from nfr_review import __version__


def test_version_is_set() -> None:
    assert __version__ == "0.1.0"
