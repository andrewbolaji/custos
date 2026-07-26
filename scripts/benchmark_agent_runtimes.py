"""Benchmark native vs. LangGraph agent runtimes: end-to-end latency and
token overhead per turn.

Requires a live ANTHROPIC_API_KEY and an indexed vector store (`make up &&
make index`, or CUSTOS_VECTOR_BACKEND=pgvector with the migration applied).
Costs real API calls -- run deliberately, not in CI.

For each fixed query, runs the full request path (retrieve -> build prompt
-> agent loop run()) against both CUSTOS_AGENT_RUNTIME values, on the same
already-indexed corpus, measuring:
  - p50/p95 wall-clock latency for AgentLoop/LangGraphAgentLoop.run()
  - input_tokens/output_tokens per turn (from the Anthropic response
    usage on the single, non-tool-use call each of these queries makes),
    to check whether either runtime adds token overhead to the wire
    request itself

Prints a summary and writes docs/benchmarks/agent-runtimes.md, in the same
style as scripts/benchmark_vector_backends.py / vector-backends.md.

Usage:
    ANTHROPIC_API_KEY=... python scripts/benchmark_agent_runtimes.py
"""

from __future__ import annotations

import os
import platform
import statistics
import subprocess
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from custos.agent_runtime import build_agent_loop
from custos.embedder import LocalEmbedder
from custos.llm import ClaudeLLM, get_system_prompt
from custos.retriever import CustosRetriever
from custos.tool_registry import ToolRegistry
from custos.vector_store_config import get_vector_store

REPETITIONS = 3  # per query, per runtime -- for stable p50/p95 under real API latency

# Fixed query set, read-only-answerable (no tool use, so every call is
# exactly one messages.create()), spanning multiple corpus documents.
QUERIES = [
    "What is the PTO accrual rate for new employees?",
    "What is the 401k matching policy?",
    "What is the company code of conduct for customer interaction?",
    "How do employees request time off?",
    "What are the emergency gas leak procedures?",
    "How much does a water heater replacement cost?",
    "What is the trip fee for a diagnostic visit?",
    "What are the warranty terms for labor?",
    "How do I schedule a service call?",
    "What are your business hours?",
    "Is there a discount for senior citizens?",
    "What is the required certification for HVAC technicians?",
    "How is overtime pay calculated?",
    "What is the return policy for parts?",
    "What is the standard response time for a service request?",
]


def _now() -> float:
    return time.perf_counter()


def _percentile(values: list[float], pct: float) -> float:
    values_sorted = sorted(values)
    idx = min(len(values_sorted) - 1, int(round(pct / 100 * (len(values_sorted) - 1))))
    return values_sorted[idx]


def _hardware_info() -> str:
    system = platform.system()
    machine = platform.machine()
    try:
        cpu = subprocess.run(
            ["/usr/sbin/sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True, text=True, timeout=2, check=False,
        ).stdout.strip()
    except Exception:
        cpu = platform.processor() or "unknown"
    try:
        mem_bytes = int(
            subprocess.run(
                ["/usr/sbin/sysctl", "-n", "hw.memsize"],
                capture_output=True, text=True, timeout=2, check=False,
            ).stdout.strip()
        )
        mem_gb = round(mem_bytes / (1024**3))
    except Exception:
        mem_gb = None
    mem_str = f"{mem_gb} GB RAM" if mem_gb else "RAM unknown"
    return f"{cpu or 'CPU unknown'}, {mem_str}, {system} {platform.release()} ({machine})"


def _make_tracking_create(
    original_create: object, runtime_results: dict[str, list[float]]
) -> object:
    """Return a wrapper around messages.create() that records response.usage
    into runtime_results before returning the response unchanged.
    """

    def _tracking_create(*args: object, **kwargs: object) -> object:
        response = original_create(*args, **kwargs)  # type: ignore[operator]
        usage = getattr(response, "usage", None)
        if usage is not None:
            runtime_results["input_tokens"].append(float(usage.input_tokens))
            runtime_results["output_tokens"].append(float(usage.output_tokens))
        return response

    return _tracking_create


def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY must be set to run this benchmark.")

    embedder = LocalEmbedder()
    store = get_vector_store(vector_size=embedder.dimension)
    retriever = CustosRetriever(embedder=embedder, store=store)

    results: dict[str, dict[str, list[float]]] = {
        "native": {"latency": [], "input_tokens": [], "output_tokens": []},
        "langgraph": {"latency": [], "input_tokens": [], "output_tokens": []},
    }

    for runtime in ("native", "langgraph"):
        os.environ["CUSTOS_AGENT_RUNTIME"] = runtime
        llm = ClaudeLLM(api_key=api_key)

        # Wrap the real client call to record response.usage without
        # touching custos/llm.py or custos/agent_loop*.py -- both runtimes
        # call self._llm.client.messages.create(...) under the hood, so
        # this wrapper is transparent to either implementation.
        llm.client.messages.create = _make_tracking_create(  # type: ignore[method-assign,assignment]
            llm.client.messages.create, results[runtime]
        )

        for query in QUERIES:
            chunks = retriever.retrieve(query=query, user_permissions=["general"], k=5)
            if not chunks:
                continue
            parts = ClaudeLLM.build_prompt(get_system_prompt(), chunks)
            registry = ToolRegistry()  # no tools: isolates model-call latency/tokens

            for _ in range(REPETITIONS):
                loop = build_agent_loop(llm=llm, registry=registry)
                start = _now()
                loop.run(parts, query)
                elapsed = _now() - start
                results[runtime]["latency"].append(elapsed)

    def _p50_p95_ms(values: list[float]) -> tuple[float, float]:
        return _percentile(values, 50) * 1000, _percentile(values, 95) * 1000

    native_p50, native_p95 = _p50_p95_ms(results["native"]["latency"])
    lg_p50, lg_p95 = _p50_p95_ms(results["langgraph"]["latency"])

    native_in_tok = results["native"]["input_tokens"]
    native_out_tok = results["native"]["output_tokens"]
    lg_in_tok = results["langgraph"]["input_tokens"]
    lg_out_tok = results["langgraph"]["output_tokens"]

    print(f"native:    p50={native_p50:.0f}ms  p95={native_p95:.0f}ms")
    print(f"langgraph: p50={lg_p50:.0f}ms  p95={lg_p95:.0f}ms")
    if native_in_tok and lg_in_tok:
        print(
            f"input_tokens  mean native={statistics.mean(native_in_tok):.1f} "
            f"langgraph={statistics.mean(lg_in_tok):.1f}"
        )
        print(
            f"output_tokens mean native={statistics.mean(native_out_tok):.1f} "
            f"langgraph={statistics.mean(lg_out_tok):.1f}"
        )

    hardware = _hardware_info()
    report_path = Path(__file__).parent.parent / "docs" / "benchmarks" / "agent-runtimes.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        _render_report(
            hardware=hardware,
            num_queries=len(QUERIES),
            repetitions=REPETITIONS,
            native_p50=native_p50,
            native_p95=native_p95,
            lg_p50=lg_p50,
            lg_p95=lg_p95,
            native_in_tok=native_in_tok,
            native_out_tok=native_out_tok,
            lg_in_tok=lg_in_tok,
            lg_out_tok=lg_out_tok,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {report_path}")


def _render_report(
    *,
    hardware: str,
    num_queries: int,
    repetitions: int,
    native_p50: float,
    native_p95: float,
    lg_p50: float,
    lg_p95: float,
    native_in_tok: list[float],
    native_out_tok: list[float],
    lg_in_tok: list[float],
    lg_out_tok: list[float],
) -> str:
    usage_table_section = "Token usage was not available from this run.\n"
    if native_in_tok and lg_in_tok:
        usage_table_section = f"""| Metric | native | langgraph |
|---|---|---|
| input_tokens (mean) | {statistics.mean(native_in_tok):.1f} | {statistics.mean(lg_in_tok):.1f} |
| output_tokens (mean) | {statistics.mean(native_out_tok):.1f} | {statistics.mean(lg_out_tok):.1f} |
"""
    return f"""# Agent runtime benchmark: native vs. LangGraph

Measured, not estimated. Regenerate with `python scripts/benchmark_agent_runtimes.py`
(requires ANTHROPIC_API_KEY and an already-indexed vector store).

## Hardware

{hardware}

## Method

{num_queries} fixed, read-only-answerable queries (`scripts/benchmark_agent_runtimes.py:QUERIES`),
issued {repetitions} times per runtime against the same already-indexed
corpus and an empty tool registry, so every call is exactly one
`messages.create()` (no tool_use branching, isolating model-call latency
and token usage from tool-execution variance). Latency is wall-clock time
for `AgentLoop.run()` / `LangGraphAgentLoop.run()` around the already-
constructed client (embedding/retrieval time is excluded, matching how
`benchmark_vector_backends.py` excludes it for the vector-store comparison).

## Results

| Metric | native | langgraph |
|---|---|---|
| p50 latency | {native_p50:.0f} ms | {lg_p50:.0f} ms |
| p95 latency | {native_p95:.0f} ms | {lg_p95:.0f} ms |

{usage_table_section}

## Reading these numbers

- Both runtimes call the raw `anthropic` client directly (no LangChain
  model wrapper), so any token-count difference reflects prompt/response
  content differences, not a framework-added wrapper. If input_tokens
  and output_tokens are equal across runtimes, that means LangGraph's
  orchestration layer adds zero token overhead on the wire, only Python-side
  orchestration cost -- see docs/decisions/006-agent-runtime.md for what that
  wall-clock cost was.
- These queries deliberately avoid tool use, so this benchmark does not
  measure the cost of the tool-gating node or the multi-step loop, only the
  single-call path. Re-run with a tool-triggering query set before using
  these numbers to reason about multi-step agent latency.
"""


if __name__ == "__main__":
    main()
