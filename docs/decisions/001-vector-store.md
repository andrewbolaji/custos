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
