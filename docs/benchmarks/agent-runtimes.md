# Agent runtime benchmark: native vs. LangGraph

Measured, not estimated. Regenerate with `python scripts/benchmark_agent_runtimes.py`
(requires ANTHROPIC_API_KEY and an already-indexed vector store).

## Hardware

Intel(R) Core(TM) i9-9880H CPU @ 2.30GHz, 16 GB RAM, Darwin 25.5.0 (x86_64)

## Method

15 fixed, read-only-answerable queries (`scripts/benchmark_agent_runtimes.py:QUERIES`),
issued 3 times per runtime against the same already-indexed
corpus and an empty tool registry, so every call is exactly one
`messages.create()` (no tool_use branching, isolating model-call latency
and token usage from tool-execution variance). Latency is wall-clock time
for `AgentLoop.run()` / `LangGraphAgentLoop.run()` around the already-
constructed client (embedding/retrieval time is excluded, matching how
`benchmark_vector_backends.py` excludes it for the vector-store comparison).

## Results

| Metric | native | langgraph |
|---|---|---|
| p50 latency | 2593 ms | 2292 ms |
| p95 latency | 5867 ms | 4544 ms |

| Metric | native | langgraph |
|---|---|---|
| input_tokens (mean) | 1481.2 | 1481.2 |
| output_tokens (mean) | 110.6 | 106.8 |

## Reading these numbers

- **No measurable latency overhead from the framework.** What the numbers show is that
  langgraph's block of calls happened to see lower network/API latency
  than native's block in this one run. `scripts/benchmark_agent_runtimes.py`
  runs all of native's repetitions first, then all of langgraph's --
  sequential, not interleaved -- so anything that drifts over the run
  (API warm-up, momentary network conditions, Anthropic-side load) biases
  the comparison and is indistinguishable, in this data, from a real
  framework effect. Wall-clock time here is dominated by live network +
  model latency (seconds), which dwarfs any local graph-traversal cost
  (which should be low single-digit milliseconds for a handful of Python
  function calls and dict updates). This benchmark cannot resolve a signal that small against that much noise. Resolving a difference that small would require interleave the two runtimes per query (alternate native/langgraph
  on each of the 15 queries, not block them) and run enough repetitions
  for the p95 gap to be robust to a single slow request; this run does neither, so the ADR claims no latency winner.
- Input tokens are identical to one decimal place across 45 live calls
  per runtime (1481.2 both) -- both runtimes send the same wire request
  (same system prompt, same messages), so this is expected, not a finding.
  Output tokens differ by about 3.5 tokens on average (110.6 vs 106.8),
  which is ordinary sampling variance at temperature=0.1 across separate
  live calls to the same query, not a systematic difference attributable
  to either runtime -- there is no mechanism in either implementation that
  would change how many tokens Claude decides to generate.
- These queries deliberately avoid tool use, so this benchmark does not
  measure the cost of the tool-gating node or the multi-step loop, only the
  single-call path. Re-run with a tool-triggering query set before using
  these numbers to reason about multi-step agent latency.
