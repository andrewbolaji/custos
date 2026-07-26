# ADR-001: Vector Store

**Status:** Accepted
**Date:** 2026-07-17
**Decision:** Qdrant (primary), pluggable VectorStore interface. pgvector as documented alternate. Chroma as local-dev quick-start only.

## Context

Custos needs a vector store for retrieval-augmented generation. The choice affects deployment complexity, query performance, filtering (access control at retrieval), and alignment with the product's "private AI" thesis.

## Options considered

### Qdrant (chosen)

**Pros:**
- Purpose-built for vector search: payload filtering, quantization, HNSW tuning out of the box.
- Self-hostable (single binary or Docker). Aligns with "nothing leaves your infra," which is the product's headline promise.
- Rich filtering on payloads, which maps directly to per-user access control at the query layer (T5 in the threat model).
- Growing job-market relevance; a distinct signal on a resume next to Postgres.
- Supports named vectors, sparse vectors, and hybrid search natively.

**Cons:**
- One more service to run (not "free" the way pgvector rides on an existing Postgres).
- Smaller ecosystem than Postgres; fewer people have operated it in production.

### pgvector (documented alternate)

**Pros:**
- Reuses Postgres, which Reckon already proved. One fewer moving part.
- Familiar operational model (backups, migrations, monitoring).
- Good enough for moderate corpus sizes (sub-million vectors).

**Cons:**
- Bolted onto a row store. No native HNSW tuning, limited quantization, filtering requires index + WHERE composition that can degrade.
- Access-control filtering via SQL WHERE is doable but less ergonomic than Qdrant's payload filters.
- Does not signal "purpose-built vector search" on a resume the way a dedicated store does.

### Chroma (local-dev quick-start only)

**Pros:**
- Zero-config, in-process, great for a notebook or a first prototype.

**Cons:**
- Not production-grade for multi-user, filtered retrieval.
- No self-hosted server mode with real persistence guarantees.

## Decision

Qdrant is the primary store. The codebase defines a `VectorStore` interface (upsert, query with filter, delete) so pgvector or Chroma can be swapped in via config. Chroma ships as a convenience for local dev and tests only. pgvector is the alternate for deployments that already run Postgres and want to minimize services.

**Swap trigger:** If a deployment environment cannot run Qdrant (e.g., a managed-Postgres-only host), switch to pgvector behind the same interface. The interface makes this a config change, not a rewrite.

## Consequences

- Docker Compose includes a Qdrant container.
- The `VectorStore` interface is the contract; no retrieval code imports Qdrant directly.
- Access-control filtering (T5) is enforced via Qdrant payload filters at query time.

## Measured

*Added after implementing the pgvector alternate behind the same `VectorStore`
interface (`src/custos/vector_store_pgvector.py`). Nothing above this section
was changed; this only appends what was subsequently measured.*

**Benchmark:** 35 fixed queries against the 63-chunk/9-document demo corpus,
on identical local hardware (Intel Core i9-9880H, 16 GB RAM, macOS, both
backends as local Docker containers). Full numbers, method, and caveats:
`docs/benchmarks/vector-backends.md`.

| Metric | Qdrant | pgvector |
|---|---|---|
| p50 latency | 3.70 ms | 0.78 ms |
| p95 latency | 4.79 ms | 1.03 ms |
| recall@5 (vs. Qdrant as reference) | -- | 1.000 |

pgvector's lower latency here is more likely a transport artifact (Qdrant's
HTTP/JSON client vs. psycopg's binary wire protocol) than evidence about the
two ANN implementations -- at this corpus size neither backend's index is
under real load. recall@5 of 1.000 means the two backends returned identical
top-5 chunk sets on every query; that is expected precisely because the
corpus is small enough that both are close to exhaustive search. Re-running
at the scale where this decision actually matters (hundreds of thousands to
millions of vectors) is the next step before trusting these numbers for a
sizing decision, per the benchmark doc's own caveats.

**Which mechanism enforces the ACL, per backend:**

- **Qdrant:** `QdrantVectorStore.query()` (`src/custos/vector_store.py`) builds
  a `models.Filter` with a `MatchAny` condition on the point payload's
  `permissions` field and passes it as `query_filter=` directly into
  `query_points()`. The filter is evaluated by Qdrant itself as part of the
  same call that does ANN scoring -- there is no separate fetch-then-filter
  step. Fail-closed via a sentinel "impossible" filter when the querying
  user has no permissions, and structurally (MatchAny can't match an empty
  payload list) when a chunk is untagged.
- **pgvector:** `PgVectorStore.query()` (`src/custos/vector_store_pgvector.py`)
  adds `WHERE permissions && %s` to the same parameterized SQL `SELECT` that
  does `ORDER BY embedding <=> %s LIMIT %s` -- one round trip, one query,
  the ACL predicate and the ANN ordering evaluated together by Postgres.
  Fail-closed falls out of the `&&` (array overlap) operator itself: overlap
  against an empty array is always false in Postgres, so an empty user
  permission list or an empty/untagged chunk's `permissions` column can
  never match, with no separate sentinel case required.

Both mechanisms satisfy the same requirement (ACL evaluated inside the
candidate-fetching query, never as a Python post-filter) via the primitive
each store natively offers for it: a payload filter for Qdrant, a WHERE
clause for pgvector. The full 61-case eval suite
(`evals/suites/`) passed identically against both backends -- no
access-control eval failed on pgvector while passing on Qdrant, so this is a
confirmation, not a finding.
