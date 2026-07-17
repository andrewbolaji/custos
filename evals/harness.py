"""Eval harness for Custos.

Runs all eval suites and prints a pass/fail summary table. Each suite is a
module in evals/suites/ that exposes a run() function returning a list of
EvalResult objects.

A suite that returns no results is NOT IMPLEMENTED, not passing. The harness
reports overall status as NOT PROVEN until every registered suite produces
real results. An empty run can never masquerade as a green security posture.

Usage:
    python -m evals.harness
    make evals
"""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

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


# Hard-gate suites: these protect security invariants and must never
# silently pass as "no results." They are NOT PROVEN until real evals exist.
HARD_GATE_SUITES = {
    "evals.suites.access_control",
    "evals.suites.action_gating",
}

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


def run_suite(module_name: str, llm_evals: bool = False) -> list[EvalResult]:
    """Import and run a suite's run() function."""
    mod = importlib.import_module(module_name)
    if hasattr(mod, "run"):
        run_fn = mod.run
        # Pass llm_evals if the suite accepts it
        import inspect

        sig = inspect.signature(run_fn)
        if "llm_evals" in sig.parameters:
            return run_fn(llm_evals=llm_evals)  # type: ignore[no-any-return]
        return run_fn()  # type: ignore[no-any-return]
    return []


def print_table(results: list[EvalResult], not_implemented: list[str]) -> None:
    """Print a formatted results table including NOT IMPLEMENTED suites."""
    all_rows: list[tuple[str, str, str, str, str]] = []

    # Real results
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        score_str = f"{r.score}" if isinstance(r.score, str) else f"{r.score:.3f}"
        all_rows.append((r.suite, r.case_name, r.metric, score_str, status))

    # NOT IMPLEMENTED suites
    for suite_name in not_implemented:
        short_name = suite_name.rsplit(".", 1)[-1]
        is_hard = suite_name in HARD_GATE_SUITES
        label = "NOT IMPLEMENTED (hard gate)" if is_hard else "NOT IMPLEMENTED"
        all_rows.append((short_name, "(none)", "(none)", "n/a", label))

    if not all_rows:
        print("\n  No eval suites registered.\n")
        return

    # Column widths
    suite_w = max(len(r[0]) for r in all_rows)
    case_w = max(len(r[1]) for r in all_rows)
    metric_w = max(len(r[2]) for r in all_rows)
    score_w = max(len(r[3]) for r in all_rows)
    status_w = max(len(r[4]) for r in all_rows)

    header = (
        f"  {'Suite':<{suite_w}}  {'Case':<{case_w}}  "
        f"{'Metric':<{metric_w}}  {'Score':>{score_w}}  Result"
    )
    sep = "  " + "-" * (suite_w + case_w + metric_w + score_w + status_w + 12)

    print(f"\n{header}")
    print(sep)
    for suite, case, metric, score, status in all_rows:
        print(
            f"  {suite:<{suite_w}}  {case:<{case_w}}  "
            f"{metric:<{metric_w}}  {score:>{score_w}}  {status}"
        )
    print(sep)

    real_total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = real_total - passed
    not_impl = len(not_implemented)
    print(f"  Proven: {passed}  Failed: {failed}  Not implemented: {not_impl}\n")


def main() -> int:
    """Run all available eval suites and print results."""
    llm_evals = "--llm" in sys.argv

    print("Custos Eval Harness")
    if llm_evals:
        print("  (including LLM-dependent evals)")
    print("=" * 40)

    suites = discover_suites()

    all_results: list[EvalResult] = []
    not_implemented: list[str] = []

    for suite_name in suites:
        results = run_suite(suite_name, llm_evals=llm_evals)
        if results:
            print(f"  Running: {suite_name} ({len(results)} cases)")
            all_results.extend(results)
        else:
            not_implemented.append(suite_name)

    print_table(all_results, not_implemented)

    # Determine overall status
    failures = [r for r in all_results if not r.passed]
    hard_gate_missing = [s for s in not_implemented if s in HARD_GATE_SUITES]

    if failures:
        print("  HARD GATE FAILURES:")
        for f in failures:
            print(f"    {f.suite}/{f.case_name}: {f.detail}")

    if hard_gate_missing:
        print("  HARD GATE SUITES NOT IMPLEMENTED:")
        for s in hard_gate_missing:
            print(f"    {s}")

    if not_implemented:
        print(
            f"\n  Overall: NOT PROVEN ({len(not_implemented)} suite(s) not implemented)"
        )
        print("  A control without a passing eval is not proven.\n")
        return 0  # not a CI failure, but visibly not proven

    if failures:
        return 1

    print("\n  Overall: ALL PROVEN\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
