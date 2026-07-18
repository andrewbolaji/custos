# ADR-005: PII Detection and Redaction

**Status:** Accepted
**Date:** 2026-07-17
**Decision:** Regex-based PII redaction at answer-time and in server logs. Mask policy (typed placeholders, not block). Unconditional on all output regardless of user tier. Company-public contacts survive via allowlist. Two-tier scope: Phase 3 covers structurally unambiguous PII only.

## Context

Threat T4 (PII exposure) requires that PII never surfaces in answers, logs, or embeddings. The corpus contains synthetic employee records (hr-001.md) with SSNs, personal emails, phones, dates of birth, and salaries. Access control (T5) already gates who retrieves HR chunks, but defense-in-depth demands a second boundary: even if a retrieval filter fails or a cleared user's answer is logged, PII must not leak.

## Decision

### Where redaction happens (two boundaries)

1. **Answer-time output filter.** A step inside `resolve_response()`, which runs on the COMPLETE answer text and is the single source of truth for all output cleaning (citation stripping, dash replacement, and now PII masking). This covers both the sync path (`generate()`) and the streaming path (`run_streaming()` calls `resolve_response()` on the full buffered text before re-chunking into word-level deltas). No per-token pipeline; no straddle concern.

2. **Server log filter.** A `logging.Filter` subclass attached to the root logger at app startup. Runs the same regex set on every log record's message before it reaches the handler. No PII in logs, ever.

We do NOT redact at ingest/index time. The corpus legitimately contains PII for authorized users, and access control gates who retrieves it. Destroying data at ingest would break authorized workflows. The redaction boundary is at output, not storage.

### Policy: mask, not block (unconditional)

Replace detected PII with typed placeholders:
- `[SSN]` for Social Security numbers
- `[EMAIL]` for personal email addresses
- `[PHONE]` for personal phone numbers

Blocking an entire answer because it contains one phone number is hostile UX. Masking preserves the answer's usefulness while removing the sensitive value.

**Unconditional masking.** Every answer masks PII regardless of the requesting user's permission tier. This is defense-in-depth independent of retrieval access control (T5). Rationale:
- Clean optics: `pii_leak_rate = 0` is provable on every path, always.
- Complements T5 rather than conflicting: access control decides what chunks you see; PII redaction decides what values appear in the answer text.
- Eliminates the class of bugs where a retrieval filter gap exposes PII in output.
- Access-aware reveal for cleared users (e.g., HR staff who need to see actual SSNs) is a ROADMAP item, not Phase 3. It requires authenticated identity (Phase 4) and a per-field reveal policy, which is more complex than a blanket mask.

### Company-public contact allowlist

Not all contact info is PII. The FAQ publishes Meridian's scheduling line `(555) 555-0100`, after-hours line `(555) 555-0101`, and website `meridian-example.com`. Masking these looks broken ("Call us at [PHONE]" is useless).

The redactor maintains a small allowlist of company-public contacts:
- **Phones:** `(555) 555-0100`, `(555) 555-0101` (from faq-001.md)
- **Domains:** `meridian-example.com` (company website)

Values on the allowlist survive redaction. All other matches are masked.

**Domain allowlist note:** Allowlisting the whole `meridian-example.com` domain means every email address at that domain (e.g., `support@meridian-example.com`, `dispatch@meridian-example.com`) passes through unmasked. This is intentional: addresses at the company domain are work/directory contacts, not personal PII. The sensitive personal emails in the corpus are on `example.org` and `example.com` (RFC 2606 reserved domains used for synthetic employee records), which are NOT allowlisted and will be masked. This is a deliberate choice, not an accident.

The allowlist is a plain data structure (set/list), not regex. It is scoped to the demo corpus. In production, this would be populated from a company config, not hardcoded. Documented as a known simplification.

### Detection scope: two tiers

#### Tier 1 (Phase 3): structurally unambiguous PII

Regex targets that do not collide with operational data. Provably 100% recall on the labeled set.

| PII type | Regex target | Mask |
|----------|-------------|------|
| SSN | `\d{3}-\d{2}-\d{4}` (reserved 900+ range in corpus) | `[SSN]` |
| Email | Standard email regex; company domain (`meridian-example.com`) allowlisted, all others masked | `[EMAIL]` |
| Phone | `(\d{3}) \d{3}-\d{4}` and common variants; company lines allowlisted, all others masked | `[PHONE]` |

These patterns are unambiguous: an SSN is always an SSN, a personal email is always a personal email. No operational data in the corpus shares these formats.

#### Tier 2 (ROADMAP): context-dependent PII

PII types that collide with legitimate operational data. Naive regex would miss cases or corrupt useful answers. Deferred to a future phase with NER/disambiguation, not because they are unimportant, but because shipping a fragile detector that over-redacts operational answers is worse than honest deferral.

| PII type | Why deferred |
|----------|-------------|
| **DOB (date of birth)** | ISO dates (`YYYY-MM-DD`) also appear as start dates, policy effective dates, and service dates. Blanket date-masking corrupts useful answers. Label-dependent regex (`DOB:` prefix) misses any DOB the model paraphrases without the label. Both are fragile overclaims. |
| **Salary** | `$XX,XXX` appears in both HR records (sensitive) and pricing docs (public). Masking requires context: is this an employee record or a product price? |
| **Address** | Street addresses share format with business locations, service areas, and directions. General regex produces false positives on any line with a number and a street name. |
| **Personal names** | "James" is a name in an HR record, a greeting in a FAQ, a brand reference in product copy. Requires NER (spaCy/presidio), a 200MB model dependency with uncertain precision. |

This two-tier framing is the project's honesty discipline applied to PII: claim less, make it unbreakable.

### Pluggable component

The redactor implements a `Redactor` ABC added to `interfaces.py`:

```python
class Redactor(ABC):
    @abstractmethod
    def redact(self, text: str) -> str:
        """Return text with PII replaced by typed placeholders."""
```

`PIIRedactor` is the concrete implementation. Swapping to presidio or a cloud-based detector is a config change, not a rewrite.

### Residual risk

- **False negatives on non-standard PII formats.** A phone written as "5555550100" (no punctuation) would not match the regex. Documented, accepted for Phase 3.
- **False positives on SSN-shaped numbers.** A `\d{3}-\d{2}-\d{4}` pattern could match a non-SSN (e.g., a part number "123-45-6789"). The corpus does not contain such values. In production, a more targeted regex or NER integration would tighten this.
- **Allowlist staleness.** If the company changes its public phone number and the allowlist is not updated, the new number would be masked. Production mitigation: populate from company config, not hardcode.
- **Tier 2 PII types unmasked.** DOB, salary, address, and names are not masked in Phase 3. Access control (T5) is the primary defense for these; the redactor is a secondary boundary that currently covers Tier 1 only.

## Alternatives rejected

### Redact at ingest time
Destroys data for authorized users. Access control already gates retrieval. Redacting at ingest means even HR staff (who need actual SSNs) see masked values. Wrong boundary.

### Block (suppress entire answer)
Hostile UX. A user asking "What is the PTO policy?" gets a blank answer because an HR chunk happened to contain a phone number in a nearby section. Masking is the right trade-off.

### Access-gated masking (mask only for unprivileged users)
Couples two independent controls (access and redaction) into a fragile dependency. If the access filter has a gap, PII leaks. Defense-in-depth means unconditional masking at output, with access-aware reveal as a Phase 4 feature requiring real authentication.

### NER/spaCy for all PII types in Phase 3
200MB model dependency, new failure mode, uncertain precision on names. Overkill for Phase 3 where the target PII is structurally unambiguous. The right tool for Tier 2; premature for Tier 1.

## Files to create/modify

- `src/custos/interfaces.py` -- add `Redactor` ABC
- `src/custos/pii.py` -- `PIIRedactor` implementation
- `src/custos/llm.py` -- wire redaction into `resolve_response()`
- `src/custos/api.py` -- attach log filter at startup
- `tests/test_pii.py` -- unit tests
- `evals/suites/pii.py` -- replace stub with real eval (per-type precision/recall)
- `evals/suites/injection.py` -- replace stub with real T1 direct-injection eval
- `evals/suites/exfiltration.py` -- replace stub with real T3 eval
- Delete stubs: `evals/suites/access_control.py`, `evals/suites/limits.py` (evals already live in `retrieval.py` and `action_gating.py`; mapping recorded in THREAT_MODEL.md)
