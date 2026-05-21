# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import warnings

warnings.filterwarnings("ignore", message=r".*libmagic.*", module=r"typecode\.magic2")
warnings.filterwarnings(
    "ignore", message=r".*libarchive.*", module=r"extractcode\.libarchive2"
)
warnings.filterwarnings(
    "ignore", message=r".*Libmagic magic database.*", module=r"typecode\.magic2"
)

__version__ = "0.1.0"

__all__ = ["__version__"]
