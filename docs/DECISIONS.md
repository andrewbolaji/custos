# Architectural Decisions

## Standing Rules

| Date | Rule | Detail |
|------|------|--------|
| 2026-07-17 | Measure, do not estimate | Every numeric claim in a summary or recap comes from an actual count (wc -l, test output, ls/find), taken seconds before typing it. |
| 2026-07-17 | Verify the verification | Before trusting a check, prove it fails when it should by introducing a deliberate failure. Lock the real command and config into the build. |
| 2026-07-17 | Recap-plus-commit close-out | A Block is closed only when the commit hash is recorded in the recap. |
| 2026-07-17 | No em dashes (standing rule) | Anywhere in app, copy, or docs. Commas, periods, parentheses, or rewrite. |
| 2026-07-17 | 9th-grade reading level (standing rule) | All user-facing copy. Concrete next steps in errors. |
| 2026-07-17 | Reserved-range PII only | All synthetic PII uses RFC 2606 emails, 555-01xx phones, 900+ SSNs. No value that could match a real person. |
| 2026-07-17 | Python 3.12, not 3.14 | dbt and other tooling break on 3.14 (protobuf C-extension crash). Pin to 3.12. |
| 2026-07-17 | Secrets never touch the repo or the chat | API keys, tokens, and credentials live in git-ignored .env. Created by the human, never pasted into chat or committed. |

## Decisions

| Date | Decision | Reason |
|------|----------|--------|
| 2026-07-17 | Qdrant primary vector store (ADR-001) | Self-hostable, on-thesis for private AI, rich payload filtering for access control. pgvector documented alternate. |
| 2026-07-17 | Local embeddings default, BGE-small (ADR-002) | Documents never leave the client's infra. Privacy is the headline, not a footnote. |
| 2026-07-17 | Claude default LLM, pluggable interface (ADR-003) | Strong grounding + instruction-following. The one external hop is explicit and documented. |
| 2026-07-17 | Structural chunking with char-offset spans (ADR-004) | Citations must resolve to real document spans. No naive fixed-size splitting. |
| 2026-07-17 | Custom eval harness over promptfoo | Need fine-grained control over security evals (access control hard gates, injection payload tracking). |
| 2026-07-17 | Byte-reproducible corpus with pinned seed | Deterministic output for evals, screenshots, and interviews. Same numbers on every rebuild. |
