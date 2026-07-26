# Vector backend benchmark: Qdrant vs. pgvector

Measured, not estimated. Regenerate with `python scripts/benchmark_vector_backends.py`
(requires `make up` for Qdrant and a reachable `CUSTOS_PGVECTOR_DSN` with the
migration applied via `make migrate-pgvector`).

## Hardware

Intel(R) Core(TM) i9-9880H CPU @ 2.30GHz, 16 GB RAM, Darwin 25.5.0 (x86_64)

Both backends ran as local Docker containers (Qdrant native image; pgvector
via `pgvector/pgvector:pg17`), not bare metal, and not on the same network
segment as a production deployment would use -- these numbers characterize
the two backends *relative to each other* on identical hardware, not
absolute production latency.

## Corpus

9 documents, 63 chunks (the demo corpus,
`corpus/output/`, embedded with BAAI/bge-small-en-v1.5, dim=384).

## Method

35 fixed queries (`scripts/benchmark_vector_backends.py:QUERIES`),
spanning every document in the corpus. Each query is embedded once, then
issued 5 times per backend (k=5, full permission set, so the
comparison measures backend/ANN behavior rather than the access-control
filter) after one warmup call. Latency is wall-clock time for
`VectorStore.query()` around the already-connected client/connection (embedding
time is excluded). recall@5 for a query is
`|qdrant_top5 & pgvector_top5| / |qdrant_top5|`, i.e. Qdrant's result set is
the reference; pgvector is scored against it.

## Results

| Metric | Qdrant | pgvector |
|---|---|---|
| p50 latency | 3.70 ms | 0.78 ms |
| p95 latency | 4.79 ms | 1.03 ms |

**recall@5 (pgvector vs. Qdrant reference): 1.000**

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
