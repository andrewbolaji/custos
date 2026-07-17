# ADR-002: Embeddings

**Status:** Accepted
**Date:** 2026-07-17
**Decision:** Local embeddings by default (BGE-small or Nomic Embed). Pluggable Embedder interface. Hosted providers (OpenAI, Voyage) available but off by default.

## Context

Custos embeds document chunks for retrieval. The embedding step sees the raw document text. For a product whose headline is "private AI," sending document chunks to a third-party embedding API is a threat-model concern, not just a performance one.

## Options considered

### Local embeddings (chosen default)

Candidates: `bge-small-en-v1.5` (33M params, 384-dim), `nomic-embed-text-v1.5` (137M params, 768-dim).

**Pros:**
- Documents never leave the client's infrastructure. This is the entire privacy thesis.
- No per-token cost. Embedding a large corpus is free after the compute.
- No network dependency; indexing works offline.
- BGE-small runs on CPU in under a second per batch. Nomic is larger but still CPU-feasible for moderate corpora.

**Cons:**
- Lower benchmark scores than OpenAI `text-embedding-3-large` or Voyage on some retrieval tasks.
- Requires shipping a model file (~130MB for BGE-small, ~500MB for Nomic). Adds to container size.
- GPU accelerates throughput but is not required for demo-scale corpora.

### Hosted embeddings (available, off by default)

Candidates: OpenAI `text-embedding-3-small/large`, Voyage `voyage-3`.

**Pros:**
- Higher retrieval accuracy on public benchmarks (MTEB).
- No local model to load; lower memory footprint.

**Cons:**
- Every document chunk is sent to a third party. For a "private AI" product, this is a direct contradiction of the value proposition. A buyer asking "does my data leave my servers?" gets "yes, to OpenAI, for embedding." That is a deal-breaker for the target audience.
- Per-token cost scales with corpus size.
- Network dependency for indexing.

## Decision

Local embeddings are the default. Start with `bge-small-en-v1.5` for speed and size; evaluate Nomic if retrieval evals show BGE-small is insufficient. The `Embedder` interface (`embed(texts) -> vectors`) makes the provider swappable. A hosted provider can be enabled via config for users who accept the trade-off.

**The privacy rule:** In the default configuration, document content never leaves the deployment. The only external call is the LLM generation request (see ADR-003), and that sends assembled context, not the raw corpus.

**Swap trigger:** If retrieval eval scores (ADR-004 citation accuracy) fall below the threshold with BGE-small, try Nomic locally before reaching for a hosted provider.

## Consequences

- The Docker image includes the BGE-small model weights (~130MB).
- Indexing is CPU-bound but fast for demo-scale corpora (hundreds of docs).
- The `Embedder` interface is the contract; no retrieval code imports sentence-transformers directly.
- `.env.example` documents the `EMBEDDER_PROVIDER` variable (default: `local`).
