# Custos: Wishlist

## v1.1 (committed, after 30 days of real v1 use)

## v2 candidates (pin, do not build; need real usage data)

### v2: Semantic chunking fallback

**The idea:** Add embedding-based topic-shift detection for documents with no structural cues (raw OCR text, unformatted logs).

**Why pin, not build:** The demo corpus is well-structured (handbooks, SOPs, FAQs). Structural chunking handles it well. Semantic chunking adds complexity and a model dependency to the chunking step.

**Trigger to promote:** Retrieval evals show structural chunking misses topic shifts in unstructured documents from a real client corpus.

### v2: Re-ranking stage

**The idea:** Add a cross-encoder re-ranker between retrieval and LLM generation for higher-precision context assembly.

**Why pin, not build:** Adds latency and a second model. Measure retrieval precision first; only add re-ranking if top-k quality is insufficient.

**Trigger to promote:** Retrieval eval precision falls below 0.8 on the labeled Q-to-source set.

## v3+ candidates (need scale or customer pull)

## Business tier candidates (pricing, packaging, model)

## Skipped (deliberately not building, with reason)

## Promotion rule

An item earns a real spec when all four are true: 3+ customers (or one strong own-use reason) asked; the user problem fits one sentence; the smallest version is describable; building it does not break the existing surface. Items 6+ months old with no pull get deleted.
