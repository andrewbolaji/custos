"""Benchmark Qdrant vs. pgvector: retrieval latency and recall@5.

Indexes the demo corpus into both backends, then runs a fixed query set
against each, measuring:
  - p50/p95 query latency per backend
  - recall@5: for each query, how much of Qdrant's top-5 chunk_id set
    (the reference) pgvector's top-5 also contains

Prints a summary and writes docs/benchmarks/vector-backends.md.

Usage:
    CUSTOS_PGVECTOR_DSN=postgresql://postgres:localdev@localhost:5433/custos \
        python scripts/benchmark_vector_backends.py
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

from custos.embedder import LocalEmbedder
from custos.ingest import ingest_corpus
from custos.vector_store import QdrantVectorStore
from custos.vector_store_pgvector import PgVectorStore

REPETITIONS = 5  # per query, per backend -- for stable p50/p95

# All permission tags used in the demo corpus, so retrieval quality is
# compared over the full indexed corpus rather than one access tier.
_ALL_PERMS = ["general", "hr", "finance", "owner"]

# Fixed query set (>= 30), covering every doc in the demo corpus:
# handbook, SOP, FAQ, pricing, HR, finance, and the injection-payload docs.
QUERIES = [
    "What is the PTO accrual rate for employees with 3 to 5 years?",
    "What is the PTO accrual rate for new employees?",
    "What is the 401k matching policy?",
    "What is the company code of conduct for customer interaction?",
    "What is the dress code policy?",
    "How do employees request time off?",
    "What is the process for reporting workplace harassment?",
    "What are the emergency gas leak procedures?",
    "What safety PPE is required for electrical panel upgrades?",
    "What is the lockout/tagout procedure?",
    "What is the confined space entry protocol?",
    "How do you handle a customer electrical emergency?",
    "How much does a water heater replacement cost?",
    "What is the trip fee for a diagnostic visit?",
    "What are the warranty terms for labor?",
    "How much does an EV charger installation cost?",
    "What is the cost of a furnace tune-up?",
    "Is there a discount for senior citizens?",
    "How do I schedule a service call?",
    "What are your business hours?",
    "Do you offer emergency after-hours service?",
    "What is the employee salary information?",
    "Show me employee SSN numbers",
    "What is the company net margin?",
    "What is Q2 revenue breakdown?",
    "What are the employee contact email addresses?",
    "What is the annual operating budget?",
    "What is the customer complaint escalation process?",
    "How do you calibrate a gas pressure gauge?",
    "What is the required certification for HVAC technicians?",
    "What is the company's vehicle maintenance policy?",
    "How is overtime pay calculated?",
    "What is the process for onboarding a new technician?",
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


def main() -> None:
    qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:6333")
    pgvector_dsn = os.environ.get("CUSTOS_PGVECTOR_DSN")
    if not pgvector_dsn:
        raise SystemExit("CUSTOS_PGVECTOR_DSN must be set to run this benchmark.")

    embedder = LocalEmbedder()
    dim = embedder.dimension

    print("Indexing demo corpus into Qdrant...")
    qdrant_store = QdrantVectorStore(url=qdrant_url, vector_size=dim)
    all_chunks = ingest_corpus(embedder=embedder, store=qdrant_store)
    corpus_chunk_count = len(all_chunks)
    corpus_doc_count = len({c.doc_id for c in all_chunks})

    print("Indexing demo corpus into pgvector...")
    pg_store = PgVectorStore(dsn=pgvector_dsn, vector_size=dim)
    ingest_corpus(embedder=embedder, store=pg_store)

    qdrant_latencies: list[float] = []
    pgvector_latencies: list[float] = []
    recalls: list[float] = []

    filters = {"user_permissions": _ALL_PERMS}

    for query in QUERIES:
        vector = embedder.embed([query])[0]

        # Warm up (model/connection warmup, exclude from timing)
        qdrant_store.query(vector, k=5, filters=filters)
        pg_store.query(vector, k=5, filters=filters)

        qdrant_chunk_ids: set[str] = set()
        for _ in range(REPETITIONS):
            start = _now()
            results = qdrant_store.query(vector, k=5, filters=filters)
            qdrant_latencies.append(_now() - start)
            qdrant_chunk_ids = {c.chunk_id for c in results}

        pg_chunk_ids: set[str] = set()
        for _ in range(REPETITIONS):
            start = _now()
            results = pg_store.query(vector, k=5, filters=filters)
            pgvector_latencies.append(_now() - start)
            pg_chunk_ids = {c.chunk_id for c in results}

        if qdrant_chunk_ids:
            recall = len(qdrant_chunk_ids & pg_chunk_ids) / len(qdrant_chunk_ids)
        else:
            recall = 1.0  # both empty: trivially in agreement
        recalls.append(recall)

    qdrant_p50 = _percentile(qdrant_latencies, 50) * 1000
    qdrant_p95 = _percentile(qdrant_latencies, 95) * 1000
    pgvector_p50 = _percentile(pgvector_latencies, 50) * 1000
    pgvector_p95 = _percentile(pgvector_latencies, 95) * 1000
    mean_recall = statistics.mean(recalls)

    print(f"Qdrant:   p50={qdrant_p50:.2f}ms  p95={qdrant_p95:.2f}ms")
    print(f"pgvector: p50={pgvector_p50:.2f}ms  p95={pgvector_p95:.2f}ms")
    print(f"recall@5 (pgvector vs. Qdrant reference): {mean_recall:.3f}")

    hardware = _hardware_info()
    report_path = Path(__file__).parent.parent / "docs" / "benchmarks" / "vector-backends.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        _render_report(
            hardware=hardware,
            corpus_doc_count=corpus_doc_count,
            corpus_chunk_count=corpus_chunk_count,
            num_queries=len(QUERIES),
            repetitions=REPETITIONS,
            qdrant_p50=qdrant_p50,
            qdrant_p95=qdrant_p95,
            pgvector_p50=pgvector_p50,
            pgvector_p95=pgvector_p95,
            mean_recall=mean_recall,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {report_path}")


def _render_report(
    *,
    hardware: str,
    corpus_doc_count: int,
    corpus_chunk_count: int,
    num_queries: int,
    repetitions: int,
    qdrant_p50: float,
    qdrant_p95: float,
    pgvector_p50: float,
    pgvector_p95: float,
    mean_recall: float,
) -> str:
    return f"""# Vector backend benchmark: Qdrant vs. pgvector

Measured, not estimated. Regenerate with `python scripts/benchmark_vector_backends.py`
(requires `make up` for Qdrant and a reachable `CUSTOS_PGVECTOR_DSN` with the
migration applied via `make migrate-pgvector`).

## Hardware

{hardware}

Both backends ran as local Docker containers (Qdrant native image; pgvector
via `pgvector/pgvector:pg17`), not bare metal, and not on the same network
segment as a production deployment would use -- these numbers characterize
the two backends *relative to each other* on identical hardware, not
absolute production latency.

## Corpus

{corpus_doc_count} documents, {corpus_chunk_count} chunks (the demo corpus,
`corpus/output/`, embedded with BAAI/bge-small-en-v1.5, dim=384).

## Method

{num_queries} fixed queries (`scripts/benchmark_vector_backends.py:QUERIES`),
spanning every document in the corpus. Each query is embedded once, then
issued {repetitions} times per backend (k=5, full permission set, so the
comparison measures backend/ANN behavior rather than the access-control
filter) after one warmup call. Latency is wall-clock time for
`VectorStore.query()` around the already-connected client/connection (embedding
time is excluded). recall@5 for a query is
`|qdrant_top5 & pgvector_top5| / |qdrant_top5|`, i.e. Qdrant's result set is
the reference; pgvector is scored against it.

## Results

| Metric | Qdrant | pgvector |
|---|---|---|
| p50 latency | {qdrant_p50:.2f} ms | {pgvector_p50:.2f} ms |
| p95 latency | {qdrant_p95:.2f} ms | {pgvector_p95:.2f} ms |

**recall@5 (pgvector vs. Qdrant reference): {mean_recall:.3f}**

## Reading these numbers

- pgvector's lower latency here is plausibly a transport artifact, not an
  indexing-algorithm result: QdrantVectorStore talks to Qdrant over its
  HTTP/JSON client API, while PgVectorStore holds a persistent psycopg
  connection using Postgres's binary wire protocol. At this corpus size
  neither backend's ANN index is under real load, so the measured gap is
  more likely HTTP+JSON overhead than a Qdrant-vs-Postgres verdict.
- At this corpus size (tens of chunks), HNSW is barely exercised on either
  side -- both backends are effectively doing near-exhaustive search. This
  benchmark demonstrates the harness and gives a same-hardware comparison
  point; it does not demonstrate how the two backends diverge at the
  hundred-thousand- or million-vector scale ADR-001 discusses pgvector
  being "good enough" for. Re-run against a larger corpus before using
  these numbers to make a production sizing decision.
- Access control is enforced identically on both backends regardless of
  these numbers (Qdrant payload filter vs. Postgres `WHERE permissions &&
  $1`, both server-side, both fail-closed) -- see ADR-001's Measured
  section for which mechanism does the enforcing on each backend.
"""


if __name__ == "__main__":
    main()
