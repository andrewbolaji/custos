# Custos

A private, agentic AI assistant that answers from a business's own documents, with real citations, tool-use, and security hardening a company can actually trust.

## Why this exists

Most "chat with your docs" projects are a weekend of glue code. The hard part, and the part buyers actually care about, is trust: *Is my data safe? Can it be tricked into leaking or misbehaving?* Custos answers that with working controls and adversarial tests that prove them.

## Security posture

Security is the headline, not a footnote. Every control ships with an adversarial eval that proves it.

- **Prompt injection defense.** Direct and indirect (payloads hidden in retrieved documents). Retrieved content is data, never instructions.
- **PII detection and redaction.** At index time and at answer time. Synthetic PII in the demo corpus uses reserved ranges only (RFC 2606 emails, 555-01xx phones, never-issued SSNs).
- **Per-user access control.** Enforced at retrieval, not in the prompt. A prompt is not a security boundary.
- **Action gating.** Read-only by default. Side-effectful actions require explicit user confirmation. Stubs are labeled "(simulated)".
- **Documented threat model.** Eight threats (T1 through T8), each with a control and a passing eval. See `THREAT_MODEL.md`.

## Architecture

```
Documents -> Ingest -> Chunk -> Embed (local) -> Qdrant (self-hosted)
                                                       |
User -> Chat UI -> FastAPI -> [Access filter] -> Retrieve -> LLM (Claude)
                      |                                        |
                Agent loop -> Tools (read-only default)     Output filter -> User
```

Every arrow crossing a trust boundary is a place where a security control lives.

**Privacy by default:** documents are embedded locally (BGE-small). The vector store (Qdrant) is self-hosted. The only external call in the default config is the LLM generation request to Claude, and that is explicit and documented. A local-model option exists for deployments where nothing can leave.

## Tech stack

- **Backend:** Python 3.12, FastAPI
- **Embeddings:** BGE-small (local, pluggable)
- **Vector store:** Qdrant (self-hosted, pluggable; pgvector alternate)
- **LLM:** Claude (pluggable; GPT and local-model options)
- **Chunking:** Structural with char-offset citation spans
- **Frontend:** React/Vite chat UI
- **Evals:** Custom adversarial harness (retrieval, injection, PII, access control, action gating)
- **Infra:** Docker, GitHub Actions CI, Terraform (Phase 4)

## Quick start

```bash
# Prerequisites: Python 3.12, Docker

# Clone and install
git clone <repo-url> && cd custos
cp .env.example .env          # then fill in ANTHROPIC_API_KEY
pip install -e ".[dev]"

# Generate the demo corpus (deterministic, no API keys needed)
make corpus

# Start Qdrant
make up

# Run tests
make test

# Run the eval harness
make evals

# Lint and type check
make check
```

## Secret scanning

**CI (the real control):** GitHub Actions runs `gitleaks detect` on every push and PR. This is the actual enforcement; it blocks merges on any finding regardless of what is installed locally.

**Pre-commit hook (convenience):** A local hook runs `gitleaks protect --staged` on each commit. It lives in `.git/hooks/` and is neither cloned nor shared. To install locally:

```bash
brew install gitleaks    # one-time
# The hook is already at .git/hooks/pre-commit
```

The `.gitleaks.toml` config allowlists the corpus directory only (synthetic PII using reserved ranges). The scanner stays live on application code, tests, and evals.

## CI

GitHub Actions runs on every push:
- **Secret scan** (`gitleaks detect`) -- blocks on any finding
- **Backend** -- ruff lint, pytest, deterministic evals (with Qdrant service)
- **Frontend** -- tsc type check, vitest, production build

LLM-dependent evals (`make evals-full`) are not run in CI. They require an API key and cost ~$0.50 per run. They are run manually before releases.

## UI build

The frontend reads the API origin from `VITE_API_URL` at build time:

```bash
VITE_API_URL=https://api.your-domain.com npm run build
```

## Embed policy

The UI serves a `Content-Security-Policy: frame-ancestors` header that restricts which sites can embed the demo in an iframe. This is deliberately restrictive: without it, any site can iframe the demo and burn the daily API budget under their own branding. The allowlist is in `ui/public/_headers`.

Default (unset): `http://127.0.0.1:8000` (local dev).

## Configuration

All limits are configurable via environment variables, adjustable without a rebuild.

| Variable | Default | Purpose |
|----------|---------|---------|
| `CUSTOS_DAILY_CAP` | 150 | Daily query cap (spike/abuse protection) |
| `CUSTOS_MONTHLY_CAP` | 4000 | Monthly query cap (budget protection, the real control) |
| `CUSTOS_SESSION_QUOTA` | 25 | Per-session query limit. Not a cost control (the caps are). Prevents one visitor from consuming the whole day. At 150/day, 25 is roughly a sixth. |
| `CUSTOS_RATE_PER_MIN` | 8 | Per-IP requests per minute |
| `CUSTOS_MAX_QUERY_LEN` | 500 | Maximum query length in characters |
| `CUSTOS_CONTACT_LINE` | (unset) | Contact line appended to the session-quota message, e.g. "get in touch at andrew@example.com for a full walkthrough". Unset = no contact line. |
| `CUSTOS_ADMIN_TOKEN` | (required) | Bearer token for the admin status endpoint |
| `CUSTOS_CORS_ORIGINS` | localhost dev origins | Comma-separated allowed CORS origins |
| `CUSTOS_TRUST_PROXY` | off | Trust X-Forwarded-For (set to 1 behind Caddy in production) |
| `CUSTOS_MODEL` | claude-sonnet-4-6 | Anthropic model ID |
| `ANTHROPIC_API_KEY` | (required) | Anthropic API key. Read from environment only, never in the repo. |

## Demo corpus

A byte-reproducible set of documents for **Meridian Home Services**, a fictional HVAC/plumbing/electrical company. Pinned seed and reference date produce identical output on every run. Includes:

- General-access docs (handbook, SOPs, FAQ, pricing)
- Restricted docs (HR records with synthetic PII, financial memo)
- Injection payloads seeded in normal-looking documents (for red-team evals)

All PII is synthetic and uses reserved/invalid ranges. See `corpus/output/manifest.yaml`.

## Project docs

| Document | What it covers |
|----------|---------------|
| `ARCHITECTURE.md` | RAG + agent + security architecture |
| `THREAT_MODEL.md` | Eight threats, their controls, and the evals that prove them |
| `EVALS.md` | How we prove retrieval, injection resistance, PII handling, access control |
| `CORPUS.md` | The demo corpus plan and reproducibility rules |
| `docs/decisions/` | Architectural decision records (vector store, embeddings, LLM, chunking) |
| `docs/DECISIONS.md` | Running log of decisions and standing rules |

## Phases

| Phase | What ships | Status |
|-------|-----------|--------|
| 0 | Scaffold, demo corpus, dev environment, eval skeleton | Current |
| 1 | RAG core: retrieval + answers with real citations + chat UI | Next |
| 2 | Agentic layer: tool-use with guardrails | Planned |
| 3 | Security pillar: injection defense, PII redaction, access control, red-team report | Planned |
| 4 | Production: containerized, observability, CI/CD, deploy | Planned |
| 5 | Deploy as a hosted live demo | Planned |

## Honesty rule

Custos never claims to do something it only simulates. If a tool call is stubbed, the UI and the response say "(simulated)". No fake bookings, no fake emails, no fake calendar checks.
