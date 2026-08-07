"""Regression test: custos.rate_limiter's module-level constants must not
leak test-time values into the rest of the pytest process.

tests/test_rate_limiter.py reloads custos.rate_limiter inside a
patch.dict block to pick up test env overrides. patch.dict restores
os.environ on exit but has no way to restore a module, so without an
explicit reload-on-teardown the module-level constants stay bound to the
test values (RATE_PER_MIN 2, DAILY_CAP 5, ...) for the rest of the
process. This file's name sorts immediately after test_rate_limiter.py
(the "." in ".py" sorts before "_"), so pytest collects and runs it right
after -- if the leak exists, the real defaults asserted below are wrong
here.
"""

from __future__ import annotations

from pathlib import Path

import custos.rate_limiter as rate_limiter_module


def test_real_defaults_survive_rate_limiter_tests() -> None:
    assert rate_limiter_module.RATE_PER_MIN == 8
    assert rate_limiter_module.SESSION_QUOTA == 25
    assert rate_limiter_module.DAILY_CAP == 150
    assert rate_limiter_module.MONTHLY_CAP == 4000
    assert rate_limiter_module.MAX_QUERY_LEN == 500


def test_data_dir_is_not_the_repository_data_dir() -> None:
    """The suite must never resolve to the application's own data/ dir.

    tests/conftest.py sets CUSTOS_DATA_DIR (before custos.rate_limiter is
    first imported) so DATA_DIR binds to a throwaway temp directory instead
    of the repository's data/ directory. If that stops working -- the
    conftest is deleted, turned into a fixture, or runs too late -- this
    is the test that catches it before a test run mutates real app state
    on disk again.
    """
    repo_data_dir = Path(__file__).resolve().parent.parent / "data"
    assert rate_limiter_module.DATA_DIR.resolve() != repo_data_dir.resolve()
