"""Limit and denial-of-service evals (EVALS.md section 7, threat T7).

Measures: oversized inputs, prompt bombs, and loop bombs hit limits and fail closed.
Stub: returns no results until rate limiting and input validation are implemented.
"""

from __future__ import annotations

from evals.harness import EvalResult


def run() -> list[EvalResult]:
    """Stub. Returns empty until input limits are implemented."""
    return []
