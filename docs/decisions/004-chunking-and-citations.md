# ADR-004: Chunking Strategy and Citation Mapping

**Status:** Accepted
**Date:** 2026-07-17
**Decision:** Structural chunking (respect document headings and sections). Char-offset spans stored per chunk for exact citation resolution. No naive fixed-size splitting.

## Context

Chunking determines retrieval quality and citation accuracy. A chunk that splits mid-sentence or mid-section retrieves poorly and cites imprecisely. Custos's citation requirement is strict: every cited source must resolve to a real span in the original document. This means the mapping from chunk back to source must be exact, not approximate.

## Options considered

### Structural chunking (chosen)

Split on document structure: headings, section breaks, paragraph boundaries, list boundaries. Chunks follow the author's own organization. Each chunk stores its source metadata: document ID, section path (e.g., "Employee Handbook > PTO Policy > Accrual"), and char-offset span (start, end) in the original text.

**Pros:**
- Chunks are semantically coherent. A section about PTO stays together instead of being split mid-rule.
- Citations map to real sections a user can find in the source document.
- Char-offset spans allow the UI to highlight the exact passage, not just name the document.
- Works naturally with the demo corpus (handbooks, SOPs, FAQs all have clear structure).
- Handles varied document types: Markdown headings, PDF sections, HTML headers.

**Cons:**
- Sections can be very long (a 3-page policy section). Needs a max-chunk-size fallback that splits on paragraph or sentence boundaries within an oversized section.
- Requires a parser per document format (Markdown, PDF, HTML, TXT). More upfront work than a fixed-size splitter.
- Structural cues can be absent in poorly formatted documents (plain text with no headings).

### Fixed-size chunking (rejected)

Split every N characters (or tokens) with overlap.

**Pros:**
- Simple. One function handles all formats.
- Predictable chunk sizes for embedding models with token limits.

**Cons:**
- Splits mid-sentence, mid-paragraph, mid-section. Retrieval quality degrades.
- Citations can only say "characters 2000-2500 of document X," which is meaningless to a user.
- Overlap creates redundant embeddings and retrieval noise.
- Does not respect the document's own organization. A chunk might contain the tail of one policy and the head of another.

### Semantic chunking (considered, deferred)

Use an embedding model to detect topic shifts and split at semantic boundaries.

**Pros:**
- Adaptive to content regardless of formatting.

**Cons:**
- Adds an embedding call to the chunking step (cost and latency).
- Boundaries are model-dependent and non-deterministic.
- Harder to map back to exact source spans (the boundary is inferred, not structural).
- Overkill for well-structured documents like handbooks and SOPs.

## Decision

Structural chunking with char-offset citation spans. The chunker:

1. Parses the document into a section tree (headings, paragraphs, lists).
2. Each leaf section becomes a chunk, with metadata:
   - `doc_id`: the source document identifier.
   - `section_path`: the heading hierarchy (e.g., `["Employee Handbook", "Benefits", "PTO Policy"]`).
   - `char_start` / `char_end`: character offsets in the original text.
   - `permissions`: inherited from the document's access control metadata.
3. If a section exceeds `MAX_CHUNK_CHARS` (default: 1500 chars), it is split on paragraph or sentence boundaries, preserving the section path and adjusting offsets.
4. Plain text with no structural cues falls back to paragraph-boundary splitting.

**Citation resolution:** The LLM response includes chunk IDs. The API resolves each chunk ID to `{doc_name, section_path, char_start, char_end}`. The UI can highlight the exact span. A citation that does not resolve to a real chunk is rejected (the honesty guardrail).

**Swap trigger:** If the corpus includes documents with no structural cues (e.g., raw OCR text), add a sentence-boundary splitter as a fallback. Semantic chunking is a v2 candidate if retrieval evals show structural chunking misses topic shifts within long unstructured sections.

## Consequences

- A per-format parser is needed: Markdown, PDF (via a library like PyMuPDF), HTML, plain text.
- Chunk metadata is stored alongside the vector in Qdrant's payload (section_path, offsets, permissions).
- The retrieval eval suite (EVALS.md section 1) measures citation accuracy: does the cited span actually support the claim?
- MAX_CHUNK_CHARS is configurable. The default (1500) balances coherence with embedding model limits.
