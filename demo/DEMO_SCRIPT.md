# Custos — 30-Minute Demo Script

Read this while sharing your screen. The right-hand column is written to be
read almost verbatim. Bring-up is `make demo` (see `demo/README.md`) —
start it before the call and confirm `http://localhost:5173` loads before
anyone joins.

Personas used live: **dana** (Standard employee) and **raj** (Finance),
switched via the UI's Access selector top-right. **sam** (contractor)
exists in the corpus and its permission table (`demo/corpus/README.md`)
but is not driven live in this script — the UI's access switcher only
exposes Standard/HR/Finance, and sam's `contractor` tag isn't one of them
on purpose (see that README's "Why sam cannot see..." section). Don't
demo sam live unless someone asks; if they do, see Q&A below.

## The script

| Minute | What you do | What you say |
|---|---|---|
| 0–3 | Open the app on Standard access. Don't touch the keyboard yet. | "I want to start with the problem, not the product. Every company I've worked with has the same failure mode: the answers to real questions live in a pile of documents nobody actually reads — a handbook, a policy memo somebody sent eighteen months ago, a contract sitting in a shared drive. The obvious fix is to point an AI at all of it and let people ask questions. And that fix quietly creates two new problems nobody asked for. First, it hands every employee access to everything, because most 'chat with your docs' tools don't do document-level permissions, they just dump the whole corpus into one index. Second, when the model doesn't actually know something, it doesn't say so — it writes a fluent, confident sentence anyway. Custos is what I built to not do either of those two things. I'm going to show you both controls actually holding, live, not describe them in a slide." |
| 3–8 | Ask: "What's the travel and expense policy for booking a hotel?" Wait for the answer to stream in, then click citation chip #1 to expand it. | "This is Dana, a regular employee, on Standard access. I'm asking a plain question with a real answer in the corpus." *(after it answers)* "Notice it didn't just answer — it cited where the answer came from. This numbered chip isn't decorative." *(click it)* "That's the actual source text, not a paraphrase, not a link I have to trust — the literal span of the document the model was allowed to read to write this answer. The point I want to land here isn't 'it answered correctly.' It's that you don't have to take my word for that. You can check it yourself, every time, on every answer." |
| 8–13 | Ask: "Can I carry over unused PTO into next year?" Expand both citations. | "Now a harder one, because this corpus has a deliberate contradiction in it — the kind that actually happens in real companies when a policy changes and not every document gets updated on the same day." *(after it answers)* "Watch which document it's citing. The employee handbook says up to 10 days carry over. But there's a second document — an HR memo from November — that says starting this year, PTO does *not* carry over, and it explicitly states that it supersedes the handbook. A good answer here doesn't just pick one; it tells you which one governs and why, with both citations sitting right there so you can verify that call yourself." *(pause)* "Here's why this matters more than it looks like it does: if this answer is ever going in front of an auditor, or a new hire is making a decision based on it, 'trust me' isn't good enough. 'Here are the two documents, here's the date on each, here's which one is authoritative' is what actually holds up." |
| 13–19 | Switch Access to **Finance** (as raj). Ask: "What's the compensation band for a senior software engineer?" Show the answer + citation. Then switch Access back to **Standard** (as dana). Ask the exact same question. | "I'm switching to Raj, in Finance." *(ask the question, let it answer with real numbers from the compensation bands document)* "Real numbers, cited straight out of our compensation bands document — Finance can see that." *(switch to Standard, notice the app clears the conversation on switch)* "Notice it started a fresh conversation the moment I switched — that's deliberate, so nothing from the Finance view carries over. Now I'm Dana again, standard access, same exact question." *(ask it)* "Different answer — actually, no answer at all, because there isn't one it's allowed to give. And I want to be precise about what just happened, because it's the whole point of this section: Dana did not get a *filtered* answer. Dana's query never retrieved the compensation document in the first place. The permission check isn't a rule the model is following — it's a filter inside the query to the vector database, before the model ever sees a token of that document. There was nothing here for the model to be talked out of, because it was never in the room." |
| 19–24 | Ask: "Can you pull up the recent customer support tickets?" or similar, so a ticket with a customer email surfaces. Point at the masked email. Then ask about ticket #4869 / recent data export requests so the flagged ticket surfaces — point at the red "Blocked" row under the answer. Then, in the same or a new message, ask directly: "Draft an email to a customer confirming their refund and send it." When the confirmation card appears, click **Reject**. | "First — see that `[EMAIL]` in the answer? That's a real customer email address in the source ticket, automatically masked before it ever reached me, regardless of who's asking." *(ask about ticket #4869)* "This next one is a real, on-file security incident, kept in the corpus on purpose. A submission came in through our contact form with a hidden instruction buried in it — the kind of thing an attacker plants hoping an AI assistant will read it as a command instead of as data. See this red line? *(point)* The system caught it and stripped it out before the model ever saw it — that's not me describing a control, that's the control firing, right now, on this exact request." *(ask it to draft-and-send an email)* "Now I'm asking directly, in plain English, for the assistant to send an email. Watch what happens." *(confirmation card appears)* "It drafted it — and stopped. Nothing sends until I approve this card. I'm going to reject it." *(click Reject)* "Nothing happened. No email went out. And here's the connection to what you just saw a minute ago: it doesn't matter whether the request to send something external comes from me typing it, or from an instruction hidden inside a document the system retrieved — like the one we just watched get caught. The model can *propose* an action. It cannot *take* one. That gate does not care who or what asked." |
| 24–28 | Ask: "What is our parental leave policy?" Let it answer. Then stop talking for a few seconds. | *(ask the question, let the answer come back)* "It doesn't know. There's nothing about parental leave anywhere in this corpus, and it's telling me that instead of guessing." *(pause, actually pause — three or four seconds of silence)* "I want to sit on that for a second, because it's the actual argument, not a footnote. Every other demo you're going to see this quarter ends on the system successfully answering something. That's the whole show — look, it worked. A system that knows how to say 'I don't know' is the only kind you can trust the rest of the time it *does* answer. If this thing were willing to guess about parental leave, it would be willing to guess about your contract terms, your compensation numbers, your customer data. It isn't, and you just watched it not do that, on a completely ordinary question, with no trick involved." |
| 28–30 | Switch to the terminal or repo view. | "Everything you just watched runs from a clone of this repository — `make demo` and it's up, we timed it, it's well under our three-minute budget on a laptop. It installs into your own AWS account from a Terraform module that's in this same repo, not ours — you own the infrastructure from the first resource created, and you can tear it down with one command when you're done evaluating it. And the questionnaire your security team is going to send us next week — I know, because it's always next week — is already filled out, sitting in `docs/SECURITY_QUESTIONNAIRE.md`, answered against the actual code, not marketing copy, with a real limitations section instead of every row marked green." |

## If something breaks

Assume the audience is watching. Say the line, keep moving.

| Failure | How you'll notice | What to say while you handle it |
|---|---|---|
| A container never came up (`make demo` hung or errored) | The terminal prints which step it's stuck on before it ever gets to "Demo ready" — `make demo` logs one status line per step for exactly this reason. `http://localhost:5173` won't load. | "Let me flip to a recording of this exact flow from this morning while this catches up" — have `demo/README.md`'s timed run, or a screen recording, ready as a fallback before you present. |
| Ingest didn't finish / index shows degraded | `/api/health` returns 503; the UI will show a connection or "temporarily unavailable" message instead of an answer. | "This is the readiness gate doing its job — it won't serve traffic until the index is actually complete, which is exactly the behavior you want in production. Give it a few seconds." Re-run `make demo` (idempotent) if it doesn't clear. |
| The model API is slow or erroring (real key, real outage) | Streaming stalls with no tokens, or an error banner appears in the chat. | "That's Anthropic's API, not our access control or redaction — those run before this call and already did their job. Let's try again," and if it doesn't recover in a few seconds, move to the next section and circle back. |
| A citation chip doesn't expand, or the snippet looks wrong | Chip click does nothing, or the expanded text doesn't match what you expect. | "The citation is still a real character span into the source document — let me open the file directly," and open the relevant `demo/corpus/*.md` file to make the same point without the UI affordance. |
| Persona/access mix-up (wrong access selected, unexpected answer) | The answer doesn't match what you just narrated (e.g., Dana got Finance-only content, or vice versa). | Check the Access selector top-right before continuing — "Let me confirm which access level I'm on" is a completely normal thing to say out loud and costs you nothing. Re-ask after correcting it. |

**On the injection-and-block step (minutes 19–24) specifically:** the
"Blocked" guardrail row is deterministic — it fires from a heuristic
pattern match at retrieval time, not from model judgment, so it will show
up the same way every run. The confirmation-card block on the direct
"send an email" ask is also deterministic — every side-effectful tool call
gates, full stop, regardless of who or what asked for it. What is *not*
scripted is whether the model, unprompted, ever tries to act on the
surviving (undetected) half of the planted instruction in ticket #4869 —
that depends on the model's own judgment on the day, and this script does
not depend on it happening. If it does happen, it is a bonus beat: point
at the same confirmation card pattern and note it caught that too.

## Questions you will get, and the answers

**What does this cost to run?** At rest, effectively nothing — Qdrant and
the app are self-hosted containers. Per query, Sonnet-class pricing on a
retrieval-augmented prompt runs a fraction of a cent; `src/custos/rate_limiter.py`
estimates roughly $0.03 per query, and that estimate is exactly what backs
the live daily/monthly spend caps described below.

**What happens when the model provider has an outage?** Retrieval, access
control, and PII redaction all run independently of the model call — an
Anthropic outage means the generation step fails and the user sees a clean
error, not a security regression. Nothing about the outage changes what a
user could retrieve or extract during it. For customers who need the model
call to never leave AWS at all, the Terraform module supports
`llm_provider = "bedrock"`, which also removes the standing API key
entirely — see `deploy/PREREQUISITES.md`.

**How do you know the retrieval is any good?** We measure it, not just
assert it — `docs/benchmarks/vector-backends.md` has the methodology, and
`evals/suites/retrieval.py` is the eval that has to keep passing. This demo
corpus is intentionally small enough (16 documents) that you watched the
system choose the right one in front of you, more than once, in the last
twenty minutes.

**Who can see the logs?** Whoever operates the deployment — same as any
self-hosted service. Logs are scrubbed of PII before they're written
(`PIIFormatter` in `src/custos/api.py`, backed by the same redactor that
masks answers), and in the standard AWS deployment they live in CloudWatch
under your account, not ours, retained for the number of days you specify
(`log_retention_days` in the Terraform module, 7 by default).

**What stops someone from just hammering this with requests?** The honest
answer is narrower than "there's no rate limiting" and narrower than "it's
fully solved" — both are wrong. Per `src/custos/rate_limiter.py`: there's a
per-IP limit (`CUSTOS_RATE_PER_MIN`, 8/minute by default) and a per-session
quota (`CUSTOS_SESSION_QUOTA`, 25 questions by default), plus a two-tier
daily and monthly spend cap (`CUSTOS_DAILY_CAP` / `CUSTOS_MONTHLY_CAP`).
The daily and monthly counters persist to disk, so they survive a container
restart — that's the real budget control. The per-IP and per-session
counters do not persist; they're in memory and reset on restart, which is
fine for their job (stopping a burst, not tracking a budget). None of these
three are tied to an authenticated user identity, because this build has no
per-user login yet — see the next answer.

**What is NOT built yet?** Real per-user authentication. Today,
`user_permissions` is supplied by the client on each request — documented
plainly in `THREAT_MODEL.md`'s "Client-supplied trust boundaries" section
and in the API's own docstring, not discovered by us after the fact. That
is the honest reason this demo uses personas instead of logins, and it's
also exactly the gap real SSO/IdP integration closes without touching the
access-control mechanism itself, since that mechanism already takes a
permission list as input — it just currently trusts the caller to supply
the right one. Tier 2 PII (address, date of birth, salary figures, personal
names) is also not masked yet, for a stated reason, not an oversight — see
`docs/SECURITY_QUESTIONNAIRE.md` section 10 for the full list and why each
gap is scoped out for now rather than silently missing.

**What if I ask it something adversarial you haven't shown me?** Ask it.
The corpus and the controls are real, not staged for these six questions —
that's the entire premise of grounding this demo in an actual running
system instead of a slide deck.

**Does the model ever train on our data?** No — Anthropic's API does not
train on customer prompts or outputs by default, and this deployment sends
no data anywhere except the single generation call per query, which is
Tier-1-PII-redacted-at-answer-time on the way back, not on the way in
(retrieval still needs real values to match against; redaction happens
before the answer reaches you). See `docs/SECURITY_QUESTIONNAIRE.md`'s "AI
and model-specific risk" section for the subprocessor detail.

**Can we run this fully air-gapped, no internet at all?** Not today,
honestly — and the reason is specific, not hand-waved. The AWS module's
container also runs a Qdrant sidecar pulled from Docker Hub, which an
air-gapped subnet can't reach, so `enable_egress = false` is blocked at
`terraform plan` time for every model provider, Bedrock included. See
`deploy/PREREQUISITES.md`'s "Network and egress" section for exactly what
closing that gap would take.
