# ADR-003: LLM Provider

**Status:** Accepted
**Date:** 2026-07-17
**Decision:** Claude as the default LLM. Pluggable provider interface. Local-model option documented as a premium "nothing leaves" tier.

## Context

Custos uses an LLM to generate grounded answers from retrieved context. The LLM call is the one place in the default config where data leaves the deployment: the assembled context (system prompt + retrieved chunks + user query) is sent to an external API. This is a deliberate, explicit trade-off.

## Options considered

### Claude (chosen default)

**Pros:**
- Strong instruction-following and grounding. Handles "answer only from the provided context" reliably.
- Good at structured output (citations with source + span).
- Large context window (200K) gives headroom for retrieved chunks without aggressive truncation.
- Anthropic's usage policies align with enterprise privacy expectations (no training on API inputs by default).
- Resume signal: building on the Claude API for an Anthropic-adjacent portfolio piece is coherent.

**Cons:**
- External API call. The assembled context (not the raw corpus, but the relevant chunks) leaves the deployment.
- Per-token cost.
- Vendor dependency (mitigated by the pluggable interface).

### GPT (documented alternate)

**Pros:**
- Broadly available. Many teams already have OpenAI API access.
- Strong tool-use / function-calling support.

**Cons:**
- Same external-call trade-off as Claude.
- OpenAI's data policies have been less clear historically (though the API has a no-training default now).

### Local model (documented as premium tier)

Candidates: Llama 3, Mistral, Phi-3 via Ollama or vLLM.

**Pros:**
- True "nothing leaves" deployment. Zero external calls. The entire pipeline runs on-premises.
- No per-token cost.

**Cons:**
- Requires GPU hardware for acceptable latency.
- Smaller models produce lower-quality grounded answers and weaker tool-use.
- Operational complexity (model serving, memory management, updates).

## Decision

Claude is the default. The codebase defines an `LLM` interface (`generate(system, context, query) -> answer + citations`) so GPT, local models, or future providers can be swapped via config.

**The one external hop:** In the default configuration, the only data that leaves the deployment is the LLM request (system prompt + retrieved chunks + user query). Documents are embedded locally (ADR-002). The vector store is self-hosted (ADR-001). This is stated explicitly in documentation and the security posture, not hidden.

**Premium "nothing leaves" tier:** A local-model config is documented for deployments where even the LLM call cannot be external. This trades answer quality for total isolation. The pluggable interface makes it the same config change.

**Swap trigger:** If a client requires zero external calls, switch to a local model. If Claude's API has availability or cost issues, GPT is the first alternate.

## Consequences

- `.env.example` documents `LLM_PROVIDER` (default: `claude`), `ANTHROPIC_API_KEY` (user-supplied).
- The `LLM` interface is the contract; no generation code imports the Anthropic SDK directly.
- README and threat model explicitly state the one-external-hop posture.
- The local-model path is tested in the eval suite but may score lower on grounding/citation evals.
