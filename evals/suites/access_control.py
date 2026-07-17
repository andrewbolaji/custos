"""Access control evals (EVALS.md section 5, threat T5).

Measures: unauthorized-retrieval rate (hard gate: must be 0).
Stub: returns no results until retriever with access filtering is implemented.
"""

from __future__ import annotations

from evals.harness import EvalResult


def run() -> list[EvalResult]:
    """Stub. Returns empty until access-filtered retriever is implemented."""
    return []
