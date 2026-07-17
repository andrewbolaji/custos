"""Eval harness for Custos.

Runs all eval suites and prints a pass/fail summary table. Each suite is a
module in evals/suites/ that exposes a run() function returning a list of
EvalResult objects.

Usage:
    python -m evals.harness
    make evals
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass


@dataclass
class EvalResult:
    """One eval case result."""

    suite: str
    case_name: str
    passed: bool
    metric: str
    score: float | str
    detail: str = ""


# Registry of eval suite modules (added as suites are implemented)
SUITE_MODULES = [
    "evals.suites.retrieval",
    "evals.suites.injection",
    "evals.suites.exfiltration",
    "evals.suites.pii",
    "evals.suites.access_control",
    "evals.suites.action_gating",
    "evals.suites.limits",
]


def discover_suites() -> list[str]:
    """Return the list of suite modules that are importable."""
    available = []
    for mod_name in SUITE_MODULES:
        try:
            importlib.import_module(mod_name)
            available.append(mod_name)
        except ImportError:
            pass
    return available


def run_suite(module_name: str) -> list[EvalResult]:
    """Import and run a suite's run() function."""
    mod = importlib.import_module(module_name)
    if hasattr(mod, "run"):
        return mod.run()  # type: ignore[no-any-return]
    return []


def print_table(results: list[EvalResult]) -> None:
    """Print a formatted results table."""
    if not results:
        print("\n  No eval results. Suites will produce results as components are implemented.\n")
        return

    # Column widths
    suite_w = max(len(r.suite) for r in results)
    case_w = max(len(r.case_name) for r in results)
    metric_w = max(len(r.metric) for r in results)

    header = (
        f"  {'Suite':<{suite_w}}  {'Case':<{case_w}}  "
        f"{'Metric':<{metric_w}}  {'Score':>8}  Result"
    )
    sep = "  " + "-" * (len(header) - 2)

    print(f"\n{header}")
    print(sep)
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        score_str = f"{r.score}" if isinstance(r.score, str) else f"{r.score:.3f}"
        print(
            f"  {r.suite:<{suite_w}}  {r.case_name:<{case_w}}  "
            f"{r.metric:<{metric_w}}  {score_str:>8}  {status}"
        )
    print(sep)

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed
    print(f"  Total: {total}  Passed: {passed}  Failed: {failed}\n")


def main() -> int:
    """Run all available eval suites and print results."""
    print("Custos Eval Harness")
    print("=" * 40)

    suites = discover_suites()
    if not suites:
        print("\n  No eval suites available yet.")
        print("  Suites will be implemented alongside their corresponding components.\n")
        return 0

    all_results: list[EvalResult] = []
    for suite_name in suites:
        print(f"\n  Running: {suite_name}")
        results = run_suite(suite_name)
        all_results.extend(results)

    print_table(all_results)

    # Hard gates: any failure returns nonzero
    failures = [r for r in all_results if not r.passed]
    if failures:
        print("  HARD GATE FAILURES:")
        for f in failures:
            print(f"    {f.suite}/{f.case_name}: {f.detail}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
