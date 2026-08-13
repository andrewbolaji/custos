# ARCHITECTURE.md — Custos

## Shape
```
                        ┌──────────────────────────────────┐
   Markdown corpus ──▶ Ingest ─▶ Chunk ─▶ Embed ─▶ Vector store │  (offline / indexing)
                        └──────────────────────────────────┘
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
- **Ingest**: load UTF-8 Markdown documents named in `manifest.yaml`, with source id, title, and permissions metadata. Other document formats are not built.
- **Chunk**: split into retrievable units; keep a stable mapping chunk → source span so citations resolve exactly.
- **PII redaction (answer/log time)**: keep the permission-gated source intact in the index, then mask supported PII in complete answers and formatted logs. Ingest-time masking is deliberately not used (ADR-005).
- **Embed + vector store**: see Task-1 decisions.
- **Access filter**: given the requesting user, restrict retrieval to permitted documents. Enforced in the query, not the prompt.
- **Retrieve + assemble**: retrieve top-k chunks and build a context block that clearly separates *instructions* (system) from *untrusted document content* (data). Re-ranking is not built.
- **LLM answer**: grounded generation; must cite; must abstain when unsupported.
- **Agent loop**: tool selection + execution with guardrails; read-only by default.
- **Guardrails**: input classification (injection/PII), output filtering (PII/leak/refusal), action gating (confirm before side effects).
- **Chat UI**: React/Vite; shows expandable citation cards with document, section, and source snippet; shows "(simulated)" labels; shows when an action needs confirmation.

## Task-1 decisions (make these before Phase 1 — one ADR each in /docs/decisions/)
1. **Vector store** — pgvector (reuse Postgres) vs Qdrant/Chroma.
2. **Embeddings** — hosted vs local (privacy trade-off is a threat-model input).
3. **LLM provider** — Claude vs GPT vs local; make it pluggable.
4. **Chunking + citation mapping** — how a citation points back to an exact span.

## Stack (reuse Reckon muscle)
Python + **FastAPI** · local embeddings · Qdrant or pgvector · **React/Vite** chat UI · custom eval harness · custom guardrails · **Docker / GitHub Actions / Terraform**. Application logs go to stdout/CloudWatch; Prometheus metrics and exporters are **not built**.

## Interfaces to keep clean (so pieces are swappable and testable)
- `Embedder` (embed(texts) -> vectors)
- `VectorStore` (upsert / query(filter, k))
- `Retriever` (retrieve(query, user) -> chunks) ← access filter lives here
- `LLM` (generate(system, context, query) -> answer+citations)
- `Guardrail` (check_input / check_output / gate_action)
- `Tool` (name, schema, side_effectful: bool, run())

Swappable interfaces are also what make the eval suite possible — you can test the retriever and guardrails in isolation.
