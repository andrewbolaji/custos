# Lessons from Roster

Private file. Not documentation. Not for clients. For Andrew, so the next project starts where this one ended.

Project: Roster (React 19 + Supabase + Tailwind v4 + Vercel)
Timeline: May 6 - June 25, 2026 (~7 weeks, 56 commits, 14 Blocks, 307 tests, 21 migrations)

---

## 1. TRAPS

Defaults that bite. The most valuable section.

---

### Schema-prefix all pgcrypto calls or they silently fail on cloud

**System:** Supabase (local vs cloud Postgres)
**Cost:** ~2 hours debugging + a dedicated migration (014) to fix every occurrence

**The trap.** `gen_random_bytes()`, `crypt()`, `digest()`, and `hmac()` work bare on local Supabase because pgcrypto is in the default search path. On cloud Supabase, pgcrypto lives in the `extensions` schema. Bare calls fail with "function does not exist." `encode()` is fine (pg_catalog). `gen_random_uuid()` is fine (core Postgres 13+). Only the pgcrypto functions break.

**The fix.** Always write `extensions.gen_random_bytes(16)`, never `gen_random_bytes(16)`. Grep the entire migrations folder for bare calls before first cloud deploy. Standing rule in DECISIONS.md from day one of the next project.

**Catching it earlier.** Before writing the first migration that uses pgcrypto: "Does this function exist in the same schema on cloud as local?"

**Generalizes to.** Any function that works locally because of search_path defaults but lives in a different schema in production. The local environment lies about what will work.

---

### Supabase RLS policies that query other RLS-protected tables create infinite recursion

**System:** Supabase Row-Level Security (Postgres RLS)
**Cost:** 2 migrations (018, 019), ~4 hours total, discovered only after deploying to cloud with real data

**The trap.** A SELECT policy on `properties` used `EXISTS (SELECT 1 FROM property_liaisons ...)`. The `property_liaisons` SELECT policy queried `properties`. Cycle: properties -> property_liaisons -> properties -> crash. Works on local with the superuser SQL editor. Fails with "stack depth limit exceeded" under a real authenticated role.

**The fix.** Route all cross-table checks in RLS policies through a `SECURITY DEFINER` function. The function runs as its definer (bypasses RLS internally), breaking the cycle. Roster uses `is_property_member(property_id)` as the single source of truth for 15 of 16 composed policies. The one exception (`properties` SELECT) uses an inline `owner_id = auth.uid()` short-circuit to avoid recursion into the function's own dependency.

**Catching it earlier.** "Does this policy's WHERE clause touch another table that also has RLS?" If yes, use a SECURITY DEFINER function.

**Generalizes to.** Any system where access-control checks are recursive (policy A depends on table B whose policy depends on table A). The fix is always: break the cycle with a privileged helper.

---

### INSERT ... RETURNING * fails when the SELECT policy uses SECURITY DEFINER

**System:** Supabase / PostgREST (`.insert().select()`)
**Cost:** 1 migration (019), ~2 hours, discovered only after the previous recursion fix

**The trap.** Supabase's `.insert().select()` compiles to `INSERT ... RETURNING *`. The `RETURNING` clause re-evaluates the SELECT policy on the just-inserted row. When the SELECT policy calls a `SECURITY DEFINER` function, that function opens a separate security context that cannot see the uncommitted row from the current transaction. The policy returns false, and PostgREST returns an empty result or an RLS violation.

**The fix.** Add a plain column check as a short-circuit before the function call: `USING (owner_id = auth.uid() OR public.is_property_member(id))`. The plain check sees the current row directly (no function call, no separate context). The function is only reached for non-owner paths (liaisons reading existing rows).

**Catching it earlier.** After writing any SELECT policy that uses a SECURITY DEFINER function: "Test INSERT ... RETURNING * against this table with a real role, not the superuser."

---

### Supabase onAuthStateChange fires INITIAL_SESSION and TOKEN_REFRESHED alongside SIGNED_IN

**System:** Supabase Auth JS SDK (v2.105+)
**Cost:** ~6 hours. 30-file fix. An infinite auth loop in production that was invisible in local dev (existing session masked it).

**The trap.** The common pattern is `getSession()` on mount + `onAuthStateChange()` for updates. But `onAuthStateChange` fires `INITIAL_SESSION` immediately (duplicating getSession), and later fires `TOKEN_REFRESHED` events. If your handler does a profile fetch on every event, you get: double-fetch on mount, re-fetch on every token refresh, and if any fetch sets state that triggers a re-render, an infinite loop. Local dev hides this because you already have a session. A fresh production database with empty tables + a first-time user exposes it.

**The fix.** Single entry point: remove `getSession()`, rely solely on `onAuthStateChange`. Filter events: `INITIAL_SESSION` and `SIGNED_IN` do a full profile load. `TOKEN_REFRESHED` updates the session object only. `SIGNED_OUT` clears immediately. Add a `userId` ref guard to prevent duplicate profile fetches. Add a timeout (15s) with a `loadError` state and retry button so the user never sees an infinite spinner.

**Catching it earlier.** Test auth on a fresh database with no existing session. This should be part of the first deploy QA, not discovered after features are built on top.

---

### `tsc --noEmit` on a root tsconfig with `files: []` checks nothing

**System:** TypeScript project references (tsc -b vs tsc --noEmit)
**Cost:** 80+ type errors accumulated silently across 8 Blocks. Two commits to fix (remove tsc -b, then restore it and fix all 42 errors).

**The trap.** The Vite scaffold creates a root `tsconfig.json` with `"files": []` and project references to `tsconfig.app.json` and `tsconfig.node.json`. Running `tsc --noEmit` against the root checks nothing (empty file list). Running `tsc -b` against the root follows the references and actually type-checks `src/`. The build script had `tsc -b && vite build`, which was correct, but during development `tsc --noEmit` was used as a quick check and reported zero errors on a codebase with 80+ real ones.

**The fix.** Use `tsc -b` always (the build command). Never use `tsc --noEmit` on a project-references setup. The standing rule from DECISIONS.md: "Before relying on a verification command, confirm empirically that it catches the class of failure it's supposed to catch by introducing a deliberate failure and watching it fail."

**Catching it earlier.** After setting up TypeScript: introduce a deliberate type error and confirm your check command catches it. Two seconds of work.

**Generalizes to.** Any CI gate or verification command. A passing gate that checks nothing is worse than a missing gate because it creates false confidence. Prove it fails when it should.

---

### `new Date('2025-06-15')` interprets the date-only string as UTC midnight, not local midnight

**System:** JavaScript Date constructor, date-fns
**Cost:** 3 separate bugs found in a pre-deploy audit. Would have caused off-by-one errors in document expiration badges at timezone boundaries.

**The trap.** Postgres `DATE` columns return `'YYYY-MM-DD'` strings. `new Date('2025-06-15')` parses this as UTC midnight. In CDT (UTC-5), that is 7pm the previous day. `differenceInDays()` (date-fns) then reports the wrong number. `differenceInCalendarDays()` is also wrong if the inputs are in different timezones.

**The fix.** Parse date-only strings with a `T00:00:00` suffix to force local interpretation: `new Date('2025-06-15T00:00:00')`. Normalize "now" with `startOfDay(new Date())`. Use `differenceInCalendarDays`, not `differenceInDays`. This matches SQL `CURRENT_DATE` behavior.

**Catching it earlier.** Establish a `parseLocalDate()` utility on day one. The first time a date-only string appears, enforce the pattern.

**Generalizes to.** Any system where dates without times cross a timezone boundary. The JavaScript Date constructor's UTC-vs-local parsing is one of the most common sources of off-by-one bugs.

---

### `zodResolver()` types do not match react-hook-form's `Resolver` type in strict mode

**System:** react-hook-form + @hookform/resolvers/zod + TypeScript strict
**Cost:** 8 `as any` casts across the codebase, each with an eslint-disable comment. Not fixable without upstream library changes.

**The trap.** `zodResolver(schema)` returns a type that does not satisfy react-hook-form's generic `Resolver<T>` under strict TypeScript. The mismatch is in the error shape. The code works perfectly at runtime. `tsc -b` rejects it.

**The fix.** Cast: `resolver: zodResolver(schema) as any` with an eslint-disable comment. Accept the cast. Do not fight the library types. This is a known issue in the ecosystem.

**Catching it earlier.** Nothing to catch. Just know it is coming and do not waste time trying to type it correctly.

---

### Supabase RPC functions not in `database.types.ts` require `as any` casts

**System:** Supabase generated types + custom SECURITY DEFINER RPCs
**Cost:** ~12 `as any` casts for RPC calls throughout the codebase

**The trap.** `supabase.rpc('my_function', params)` is type-checked against the `Functions` section of `database.types.ts`. If your RPC function is not in that section (because you wrote it by hand in a migration, not via the Supabase type generator), TypeScript rejects the call. The function works fine at runtime.

**The fix.** Either regenerate types with `supabase gen types typescript` after every migration (requires Supabase CLI and a running local instance), or cast: `(supabase.rpc as any)('my_function', params)`. Roster chose the cast because no local Supabase CLI was installed (migrations were applied via Dashboard SQL Editor).

**Catching it earlier.** Decide on day one: will you run the Supabase CLI locally for type generation, or accept manual type maintenance with casts? Both are valid. Switching mid-project is where time is wasted.

---

### Edge Function `verify_jwt = false` in config.toml is required for public endpoints

**System:** Supabase Edge Functions (Deno)
**Cost:** Minor (caught during planning), but would have been a silent 401 on every public submission

**The trap.** Supabase Edge Functions verify JWTs by default. A public endpoint (like a form submission from an unauthenticated user) gets a 401 before your code runs. The fix is in `supabase/config.toml`, not in the function code.

**The fix.** Add `[functions.my-function]` with `verify_jwt = false` to `config.toml`. If the function needs auth for some paths, verify the JWT in-function via `supabase.auth.getUser(token)` instead of relying on the gateway.

**Catching it earlier.** When planning any public-facing Edge Function: "Who calls this? Do they have a JWT?"

---

### react-hook-form `watch()` breaks React Compiler optimization

**System:** react-hook-form + React 19 Compiler
**Cost:** eslint warnings on every component using `watch()`. Minor, but the pattern is everywhere.

**The trap.** `watch()` returns a new reference on every render. The React Compiler (React 19) tries to memoize component output, but `watch()` defeats this because its return value is not memoizable. ESLint's `react-hooks/incompatible-library` rule flags it.

**The fix.** Use `useWatch()` instead of `watch()` where possible (it integrates with the Compiler). Where `useWatch()` does not fit, add `// eslint-disable-next-line react-hooks/incompatible-library` with a comment explaining why.

---

## 2. PATTERNS THAT WORKED

Solution shapes worth reusing.

---

### SECURITY DEFINER as the single RLS truth

Built `is_property_member(property_id)` as one function that answers "can this user access this property?" Used in 15 of 16 RLS policies. When the role model changed (adding liaisons), one function was updated. Every policy inherited the change. Without this, 15 separate policies would each need updating, and at least one would be missed.

**Why it worked:** Single source of truth for access control. SECURITY DEFINER bypasses RLS internally, preventing recursion. The function is the only place that knows about the owner/liaison distinction.

**Reuse as:** Any multi-role access system on Supabase. Define one function per access question. Use it in all policies.

---

### Public endpoints via SECURITY DEFINER RPCs, not direct table access

Unauthenticated users (check-in form, inspector view, application form) call SECURITY DEFINER functions that validate tokens, sanitize inputs, rate-limit, and return whitelisted fields via `jsonb_build_object`. No anon INSERT/SELECT policies on the real tables. The functions are the API surface.

**Why it worked:** PII never leaks because the function controls the response shape. Rate limiting is server-side. Token validation is server-side. A future dev cannot accidentally expose a field by changing a UI component, only by changing the SQL function.

**Reuse as:** The default pattern for any public-facing data access on Supabase.

---

### Cross-implementation invariant tests

When the same logic exists in two places (TypeScript `getPermitUrgency()` and SQL `CASE` in `inspector_get_permits`), one test runs both against an 8-input matrix and asserts they agree. F3-T17 caught a real bug: `differenceInCalendarDays` vs SQL `CURRENT_DATE - expiry_date` disagreed at timezone boundaries.

**Why it worked:** The two implementations were written independently and one was wrong. No amount of unit testing on either side alone would have caught the discrepancy. The invariant test is the only thing that did.

**Reuse as:** Any time the same calculation appears in app code and in a database query/function. Write one matrix test.

---

### Three-tier template model for compliance checklists

System templates (migration-seeded, per property_type) -> property items (operator-editable copies) -> resident completions (frozen at arrival). Template edits do not propagate to in-progress residents. Each tier is a separate table.

**Why it worked:** Operators can customize without affecting residents already in progress. New properties get sensible defaults. Auditors see exactly what each resident was shown, not what the current template says.

**Reuse as:** Any system where a template evolves but historical instances must be frozen.

---

### DECISIONS.md with extraction triggers

Every deferred extraction (e.g., "extract `createSupabaseContext` helper when a 3rd CRUD context appears") was logged with a concrete trigger condition. This prevented two failure modes: premature extraction (wasting time on abstractions that never pay off) and forgotten extraction (letting duplication compound until it is too expensive to fix).

**Why it worked:** The triggers were specific and testable ("at 3 instances" or "at 6 instances"). They were checked during planning for each new Block.

**Reuse as:** The default discipline for any "not yet, but eventually" decision.

---

### Audit-log INSERT via SECURITY DEFINER only

Users get SELECT-only on `audit_log`. All inserts go through `insert_audit_log()` or triggers. Users cannot fabricate audit entries. The audit trail is tamper-evident.

**Why it worked:** Simple, effective, and the pattern is obvious to enforce in review (any INSERT on audit_log that does not go through the function is a bug).

---

### Canvas API for EXIF stripping (no library)

Drawing an image to a canvas and exporting via `toBlob('image/jpeg')` inherently strips all EXIF metadata including GPS coordinates. No npm dependency. Always outputs JPEG regardless of input format.

**Why it worked:** Zero dependencies. Works in all browsers. Solves both compression and privacy (GPS stripping) in one step.

---

## 3. DEAD ENDS

Things tried that did not work.

---

### Inline cross-table subqueries in RLS policies

Tried writing RLS policies with `EXISTS (SELECT 1 FROM other_table WHERE ...)` where `other_table` also had RLS. Hit infinite recursion (see Trap above). Every instance had to be replaced with a SECURITY DEFINER function call.

**Do not try again.** Use SECURITY DEFINER functions from the start for any cross-table RLS check.

---

### getSession() + onAuthStateChange() dual initialization

The Supabase docs suggest both. In practice, `onAuthStateChange` fires `INITIAL_SESSION` immediately, making `getSession()` redundant. The dual pattern causes double profile fetches and, under certain conditions, infinite loops.

**Do not try again.** Use `onAuthStateChange` as the single entry point. Filter events by type.

---

### react-hook-form watch() for conditional form fields

Works functionally but breaks React Compiler optimization and triggers eslint warnings. `useWatch()` is the correct alternative.

---

### Dynamic import to avoid "circular dependency" that did not exist

Block 4 used `await import('../../lib/supabase')` in a download handler based on a theory about circular imports. Investigation showed `supabase.ts` was already imported transitively. The dynamic import added complexity for zero benefit. Switched back to a direct import.

**Do not try again.** Prove the circular dependency exists (actual error or actual import graph evidence) before adding dynamic imports.

---

## 4. DECISIONS AND THEIR TRIGGERS

Forks where X was chosen over Y. The reason, and the condition to revisit.

---

### No Supabase CLI locally; migrations via Dashboard SQL Editor

**Chose:** Manual migration application via Dashboard + manual type maintenance with `as any` casts.
**Over:** Local Supabase CLI with `supabase gen types typescript` and `supabase db push`.
**Reason:** Faster setup for a solo project. Avoided Docker dependency. Acceptable at 21 migrations.
**Revisit when:** A second developer joins, or type drift causes a runtime bug, or migration count exceeds 40. At that point, the CLI pays for itself.

---

### No email notifications in v1; Resend + Edge Functions in v1.1

**Chose:** Database-only for all notification surfaces (feedback, document expiration, incident alerts).
**Over:** Wiring Resend from day one.
**Reason:** Email adds Edge Function infrastructure. 30 days of real usage revealed which notifications actually matter. Feedback, for example, never needed email.
**Revisit when:** Building any feature where email is the primary notification channel (invitations, which did require it in v1.1).

---

### Single-owner architecture, no org/tenant table

**Chose:** `owner_id` on properties. Liaison role added later as a secondary accessor.
**Over:** Full multi-tenant org model from the start.
**Reason:** One real customer (Wrexham). The org model would have been speculative architecture.
**Revisit when:** A customer needs multiple admins with different permission levels, or white-labeling is required. The liaison pattern covers contributor access without an org table.

---

### Three separate modal components for severe incidents, not one shared modal

**Chose:** `SevereIncidentLEModal`, `SevereIncidentHotlineModal`, `ResidentAbsenceModal` as separate components.
**Over:** One `SevereIncidentModal` with conditional rendering.
**Reason:** At 3 variants with meaningfully different fields and validation, abstraction overhead costs more than duplication. Each modal is ~100 lines.
**Revisit when:** A 4th variant appears with shared structure. Extract at that point.

---

### Tailwind v4 @theme tokens, not tailwind.config.js

**Chose:** CSS-native `@theme` block in `index.css` for all design tokens.
**Over:** JavaScript-based `tailwind.config.js`.
**Reason:** Tailwind v4 ships with Vite plugin and uses CSS-native configuration. No separate PostCSS config needed.
**Revisit when:** Never, unless reverting to Tailwind v3. This is the v4 way.

---

### 30 check-ins per minute rate limit

**Chose:** 30/min per property.
**Over:** Per-user or dynamic rate limiting.
**Reason:** Generous for legitimate use (20 residents arriving simultaneously). Cheap to enforce via COUNT query.
**Revisit when:** Multi-tier customers with 60+ residents report rate limit hits during shift changes. Scale to `capacity * 3` per minute at that point.

---

## 5. WHAT WASTED TIME

Process, not code. Where hours went that produced nothing.

---

### The vacuous type-check gate wasted a full day

80+ type errors accumulated across 8 Blocks because `tsc --noEmit` on the root config checked nothing. Two separate commits (one to remove `tsc -b` from the build to unblock a deploy, one to restore it and fix all 42 remaining errors) consumed a full day. Every one of those errors would have been a 30-second fix if caught in the Block that introduced it. The total cost was at least 10x what incremental fixes would have been.

**The process fix:** After setting up any verification command, introduce a deliberate failure and confirm the command catches it. This is now a standing rule.

---

### The design system was built twice

Block 7 (v1 polish) did a comprehensive design pass: dark theme, blue accent, Inter font, extracted 5 shared primitives, added focus-visible rings to all inputs, migrated from hardcoded palette to tokens. Then a second design pass (Design v2) added serif fonts, emphasis color, masthead, left-rules. The second pass was additive and fine, but the first pass happened late (Block 7 of 7). Blocks 1-6 each included ad-hoc styling that was thrown away in Block 7.

**The process fix:** Establish the design token system in Block 1 (even if minimal: 3 surfaces, 1 accent, 1 semantic set, 1 font). Build on tokens from the start. The polish pass then refines tokens, not replaces them.

---

### Focus ring classes are copy-pasted across 30+ elements instead of living in a shared primitive or utility

The design system pass added `focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-bg` to every input, select, textarea, and button individually. This is a 90-character string duplicated 30+ times. A single CSS rule in `index.css` or a Tailwind `@apply` directive would have been one line. Changing the focus style now requires a 30-file find-and-replace.

**The process fix:** When adding a style to "all inputs," add it to the base element style once, not to each component.

---

### Three RLS bugs found only on first production deploy, invisible to 260+ tests

The auth loop, the policy recursion, and the INSERT RETURNING failure were all invisible locally and in the mocked test suite. Each required a migration to fix. Total: ~8 hours of debugging, 3 migrations, 30+ test file updates. Every one would have been caught by testing against a real Supabase instance with real roles (not the superuser SQL editor) during development.

**The process fix:** After any migration that adds or changes an RLS policy, test it against the real database as the actual role (`set role authenticated` + `request.jwt.claims`), not the superuser. The mocked Vitest suite cannot exercise RLS. It is structurally blind to this class of bug.

---

### Numeric claims in recaps drifted six times

Line counts, file counts, and test counts in Block recaps were wrong six separate times across the project. Each discrepancy required a re-review. The fix was trivial (run `wc -l`, count the actual files, read vitest output), but the re-reviews were not.

**The process fix:** Standing rule: every number in a recap must come from a measurement taken seconds before typing it.

---

## 6. SPEC AND REVIEW PROCESS

This project was built from a written spec (ROSTER_SPEC.md, ~600 lines) with a human (Andrew) reviewing after each Block. Honest assessment.

---

### Where the spec was wrong, ambiguous, or missing

1. **The spec said `users` table; Supabase idiom is `profiles`.** Caught in Block 1 planning. Trivial to fix, but it is the kind of thing that wastes 20 minutes if not caught.

2. **The spec did not address the auth initialization pattern.** It specified "Supabase Auth" but said nothing about `getSession` vs `onAuthStateChange`, event filtering, or the infinite-loop risk. This was the single most expensive omission: 6 hours and 30 files to fix.

3. **The spec assumed `parole_officer` naming.** An advisor review in v1.1 pointed out that not all residents under supervision are parolees. Renaming to `case_manager` touched the DB schema, all forms, all display pages, and tests. A spec that said "generic supervision contact" from the start would have avoided the rename.

4. **The spec did not specify HEIC/WEBP support for file uploads.** HEIC is the default iPhone photo format. Blocking it would have failed real users on day one. Caught during advisor review, not by the spec.

5. **The spec did not address timezone handling for date-only values.** Three bugs resulted. A spec section on "date-only strings are parsed as local midnight" would have prevented all three.

6. **The spec did not specify the RLS pattern.** It said "row-level security" but not the cross-table recursion risk or the SECURITY DEFINER pattern. This is arguably too low-level for a spec, but the cost was 3 migrations.

**What the next spec should contain:**
- Auth initialization pattern (single entry point, event filtering, timeout behavior)
- Date handling convention (local vs UTC, parsing strategy for date-only strings)
- File upload format list (explicitly include HEIC/WEBP)
- RLS pattern decision (inline vs SECURITY DEFINER) before the first migration
- Naming conventions for domain terms (generic names that survive domain learning)

---

### Review catches that would have shipped unsupervised

These are specific things the human review caught that the AI (me) would have shipped past without the review step.

1. **I misdiagnosed a focus ring as a broken border.** During the design system pass, I saw `focus-visible` outline styles on inputs and interpreted them as visual inconsistencies to "fix." I flattened them into the component styles instead of preserving the browser's accessibility focus indicator pattern. Andrew's review caught this. Without it, I would have shipped an accessibility regression: keyboard users would have lost visible focus indicators on some elements. The root cause is that I optimized for visual consistency without understanding that the ring was an intentional accessibility feature, not a styling artifact.

2. **I flattened design tokens into raw values.** During early Blocks, I wrote classes like `bg-[#1a1a18]` and `text-[#ededea]` instead of using the `@theme` tokens (`bg-surface`, `text-text`). The design system pass (Block 7) had to do a 47-file migration from hardcoded values to tokens. Andrew caught individual instances during reviews, but the systemic pattern was not fully addressed until the dedicated design pass. The fix was to establish tokens in Block 1 and enforce them immediately.

3. **I over-counted in recaps.** Six times across the project, I reported a number (lines, files, tests) that was wrong. Each time, the number was plausible and would have gone into the record unchallenged without Andrew's verification. The standing rule "measure, do not estimate" exists because of this.

4. **I reported an "8-minute reading level audit" that had only covered empty states.** The Block 7 audit claimed comprehensive coverage but had skipped modals, validation messages, labels, and button text. Andrew's verification request ("enumerate at least 20 specific items you scanned") caught this. Without the enumeration request, incomplete audit coverage would have shipped as "complete."

5. **I wrote a liaison RLS policy using an inline property_liaisons subquery instead of the `is_property_member()` helper that every other policy uses.** Both the implementer (me) and the reviewer (the strategic AI) checked the policy's logic in isolation and approved it. It only failed on the live-role database walk because `property_liaisons` SELECT is owner-only, so the subquery silently returned nothing for liaison users. This is a pattern-matching failure: I should have checked "does this match how the codebase already does this?" before checking "is the logic correct in isolation?"

**What would have prevented these:**
- Focus ring: A standing rule in the spec or framework: "Do not remove or replace `focus-visible` styles without understanding their accessibility purpose. If you see a ring or outline on focus, it is probably intentional."
- Design tokens: Establish the token system in Block 1. Add a lint rule or review checklist item: "No hex values in className strings."
- Numeric claims: The standing rule works. Enforce it.
- Audit coverage: Always request enumeration for audit-style claims.
- Pattern matching: The framework now includes "Match the established pattern, or state why not" as a standing rule. Check new instances against existing siblings, not just against their own logic.

---

### What should a spec for the next project contain that this one did not

1. **An auth initialization section.** Not just "use Supabase Auth" but the specific event-handling pattern, the timeout strategy, and the recovery flow.

2. **A date-handling convention.** One paragraph: "Date-only strings are parsed with `T00:00:00` suffix. All date comparison uses `startOfDay`. Utility: `parseLocalDate()`."

3. **A design token decision in the stack section.** Not just "Tailwind" but "Tailwind v4 with `@theme` tokens. No hex values in component classes. Tokens established in Block 1."

4. **An RLS pattern decision.** "Cross-table access checks use SECURITY DEFINER functions. No inline subqueries against RLS-protected tables in policy definitions."

5. **File upload format list.** Explicitly: JPEG, PNG, PDF, HEIC, WEBP. Not "images" (which implies only JPEG/PNG).

6. **A "what the AI will get wrong" section.** Based on this project: visual accessibility features mistaken for bugs, design tokens bypassed for raw values, numeric claims that are estimates not measurements, audit coverage that is partial not comprehensive, new instances that deviate from established patterns. These are predictable AI failure modes. Name them in the spec so the reviewer knows where to look.

---

## Appendix: Commit evidence

Key fix commits referenced above:
- `0e06910` Fix pgcrypto schema prefix
- `fde1af3` Fix RLS infinite recursion (migration 018)
- `09a9c87` Fix INSERT RETURNING RLS failure (migration 019)
- `dfecd5d` Fix auth loop (30 files, 6 hours)
- `0e56ef4` Fix Vercel build: tsc -b compatibility
- `280a380` Restore tsc -b, fix 42 type errors
- `1000390` Pre-deploy: date-only string audit (3 bugs)
- `c5015c1` Fix liaison RLS on applicants
- `ba11f08` Block 7 copy fixes from reading level audit
- `b81a769` Design system pass (47-file token migration)
