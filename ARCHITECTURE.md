# ARCHITECTURE.md — Custos

## Shape
```
                        ┌─────────────────────────────────────────────┐
   Documents ──▶ Ingest ─▶ Chunk ─▶ Redact PII ─▶ Embed ─▶ Vector store │  (offline / indexing)
                        └─────────────────────────────────────────────┘
                                                          │
 User ──▶ Chat UI ──▶ API (FastAPI) ──▶ [Access filter] ──▶ Retrieve ──▶ Assemble context
                                    │                                        │
                                    │                              ┌─────────▼─────────┐
                                    │                              │  LLM (grounded)   │
                                    │        ┌── Guardrails ◀───────┤  answer + cite    │
                                    ▼        ▼                      └─────────┬─────────┘
                              Agent loop ─▶ Tools (read-only default;         │
                              (tool-use)    ask before side effects)         ▼
                                                                     Output PII filter ─▶ User
```
Every arrow crossing a trust boundary (document text in, user input in, answer out, tool call out) is a place where a security control lives. See `THREAT_MODEL.md`.

## Components
- **Ingest**: load documents (PDF, MD, TXT, HTML, maybe email/CSV). Normalize to text + metadata (source id, permissions, timestamps).
- **Chunk**: split into retrievable units; keep a stable mapping chunk → source span so citations resolve exactly.
- **PII redaction (index-time)**: detect + mask PII before it ever lands in the vector store (decision: redact at index time, at answer time, or both — default both).
- **Embed + vector store**: see Task-1 decisions.
- **Access filter**: given the requesting user, restrict retrieval to permitted documents. Enforced in the query, not the prompt.
- **Retrieve + assemble**: top-k with re-ranking (optional); build a context block that clearly separates *instructions* (system) from *untrusted document content* (data).
- **LLM answer**: grounded generation; must cite; must abstain when unsupported.
- **Agent loop**: tool selection + execution with guardrails; read-only by default.
- **Guardrails**: input classification (injection/PII), output filtering (PII/leak/refusal), action gating (confirm before side effects).
- **Chat UI**: React/Vite; shows citations as clickable source spans; shows "(simulated)" labels; shows when an action needs confirmation.

## Task-1 decisions (make these before Phase 1 — one ADR each in /docs/decisions/)
1. **Vector store** — pgvector (reuse Postgres) vs Qdrant/Chroma.
2. **Embeddings** — hosted vs local (privacy trade-off is a threat-model input).
3. **LLM provider** — Claude vs GPT vs local; make it pluggable.
4. **Chunking + citation mapping** — how a citation points back to an exact span.

## Stack (reuse Reckon muscle)
Python + **FastAPI** · embeddings + vector store (per decision) · **React/Vite** chat UI · evals harness (promptfoo or custom) · guardrails (custom + a library) · **Docker / GitHub Actions / Terraform** reusing Reckon patterns · observability via Prometheus (reuse). Postgres if pgvector is chosen — which also lets dbt-style tests reuse Reckon habits.

## Interfaces to keep clean (so pieces are swappable and testable)
- `Embedder` (embed(texts) -> vectors)
- `VectorStore` (upsert / query(filter, k))
- `Retriever` (retrieve(query, user) -> chunks) ← access filter lives here
- `LLM` (generate(system, context, query) -> answer+citations)
- `Guardrail` (check_input / check_output / gate_action)
- `Tool` (name, schema, side_effectful: bool, run())

Swappable interfaces are also what make the eval suite possible — you can test the retriever and guardrails in isolation.
