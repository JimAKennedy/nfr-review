# SPDX-License-Identifier: MIT
"""Clean example package — no PII, no tracking, no internal references."""

__version__ = "1.0.0"


def main() -> None:
    """Entry point for the clean-example CLI."""
    print(f"clean-example v{__version__}")  # noqa: T201
