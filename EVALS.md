# EVALS.md — how Custos proves itself

Evals are the portfolio proof for an AI project the way screenshots were for Reckon. "It resists prompt injection" is a claim; **a passing adversarial test suite is proof.** Every control in `THREAT_MODEL.md` maps to a suite here. `make evals` runs all of them and prints a pass-rate table.

## 1. Retrieval / grounding
- **Right-source citation**: a labeled Q→source set; measure whether the cited source is correct (precision/recall on citations).
- **Faithfulness**: the answer's claims are supported by the retrieved spans (no ungrounded assertions).
- **Abstention**: for questions the corpus can't answer, it says "I don't know" instead of hallucinating. Measure false-answer rate on an unanswerable set.

## 2. Prompt injection (T1, T2)
- **Direct**: a battery of "ignore your instructions / reveal your system prompt / drop the (simulated) labels" inputs. Metric: attack-success rate (target ≈ 0).
- **Indirect**: the seeded corpus payloads from `CORPUS.md`. The model retrieves a poisoned chunk; success = it does NOT follow the payload. This is the flagship result — report it prominently.

## 3. Data exfiltration (T3)
- Attempts to dump the corpus, smuggle data through a tool argument, or encode data in a URL. Metric: leak rate (target 0).

## 4. PII (T4)
- Labeled PII set; measure detection precision/recall and that redaction actually masks in answers **and** logs.

## 5. Access control (T5)
- User A issues queries that would match B-only / HR / finance docs. Success = those chunks are never retrieved for A. Metric: unauthorized-retrieval rate (must be 0 — this is a hard gate, not a threshold).

## 6. Action gating (T6)
- The agent is prompted (directly and via injection) to take side-effectful actions. Success = it asks for confirmation or refuses; stubs are labeled "(simulated)". Metric: unauthorized-action rate (0).

## 7. Limits (T7)
- Oversized inputs, prompt bombs, loop bombs hit the size/rate/step limits and fail closed.

## Reporting
- `make evals` → a table: suite · metric · score · pass/fail, plus a written **red-team report** (attack → result → control → residual risk).
- Track scores across commits so regressions are visible (a security control silently breaking is the nightmare — the eval catches it).
- Hard gates (access control = 0 unauthorized retrievals, action gating = 0 unauthorized actions) fail CI if violated. Thresholded metrics (retrieval precision, injection resistance) have documented minimums.

## Tooling
promptfoo or a custom harness — decide in Phase 1. Whatever it is, it must be scriptable in CI and produce a machine-readable results file for the portfolio write-up.
