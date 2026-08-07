"""Point the test suite at a throwaway data directory before anything
in `custos` gets imported.

`custos.rate_limiter` reads `CUSTOS_DATA_DIR` at *module import time* into
a module-level constant (`DATA_DIR`, and `COUNTERS_FILE` derived from it),
defaulting to the repository's own `data/` directory. `custos.api` then
instantiates a `RateLimiter()` singleton at its own import time, which
reads and writes `COUNTERS_FILE` immediately.

A fixture cannot fix this, no matter how it's scoped or how "autouse" it
is: fixtures run when a test executes, and by then pytest has already
imported every test module during collection, which already imported
`custos.rate_limiter` (directly or via `custos.api`), which already bound
`DATA_DIR` to whatever `CUSTOS_DATA_DIR` was -- or wasn't -- at that
moment. Setting the environment variable afterward sets a variable that
nothing will read again.

The only point early enough is top-level code in this file. pytest imports
a directory's `conftest.py` before it imports any test module in that
directory, and `testpaths = ["tests"]` in pyproject.toml pins collection
to this directory, so this file runs before `custos.rate_limiter` or
`custos.api` is ever imported by the suite.

If someone "cleans this up" into a fixture, the effect will be silent:
every test that doesn't explicitly patch `CUSTOS_DATA_DIR` itself goes
back to reading and writing the real `data/counters.json` on disk.

`os.environ.setdefault` (not a plain assignment) is used so that anyone
who has deliberately set `CUSTOS_DATA_DIR` themselves -- e.g. to point at
a specific fixture directory -- still wins.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

_TEST_DATA_DIR = tempfile.mkdtemp(prefix="custos-test-data-")
os.environ.setdefault("CUSTOS_DATA_DIR", _TEST_DATA_DIR)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Remove the throwaway data directory once the whole session ends."""
    shutil.rmtree(_TEST_DATA_DIR, ignore_errors=True)
