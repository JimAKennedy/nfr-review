"""Internal error types for output formatters.

Lives in its own module so ``csv.py`` and ``jsonl.py`` can import without a
circular dependency through ``nfr_review.output.__init__``.
"""

from __future__ import annotations


class OutputError(Exception):
    """Raised when an output file cannot be written.

    Always carries the target path in its message so the engine can surface
    actionable failure information in the run summary (S01 verification).
    """


__all__ = ["OutputError"]
