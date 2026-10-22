"""Shared test set-up: one numba cache per pytest worker."""

import os
from pathlib import Path

# librosa compiles with numba and caches the machine code next to its own sources. In a fresh
# environment, pytest-xdist workers compiling the same function at once wrote a corrupt cache (a
# segfault in beat tracking, every later run included). Each worker of this checkout gets its own.
_worker = os.environ.get("PYTEST_XDIST_WORKER")
if _worker and "NUMBA_CACHE_DIR" not in os.environ:
    os.environ["NUMBA_CACHE_DIR"] = str(Path(__file__).resolve().parents[1] / ".numba-cache" / _worker)
